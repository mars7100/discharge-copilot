import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import sessions
from api.schemas import Approve, Ask, CreateSession, Propose
from api.streaming import FIXTURES, stream_load
from core.export import to_markdown
from core.review_graph import ask
from core.revise import accept, propose

app = FastAPI()
UI_DIR = Path(os.environ.get("DISCHARGE_UI_DIR", Path(__file__).parent.parent / "frontend" / "dist"))
TEMPLATE = Path(__file__).parent.parent / "core" / "template.json"


@app.get("/api/cases")
def list_cases():
    return {"cases": sorted(p.name for p in FIXTURES.iterdir() if p.is_dir() and not p.name.startswith("."))}


@app.get("/api/template")
def get_template():
    return {"sections": json.loads(TEMPLATE.read_text())["sections"]}


@app.post("/api/sessions", status_code=201)
def create_session(body: CreateSession):
    if body.case_id not in list_cases()["cases"]:  # also blocks "..", absolute paths
        raise HTTPException(404, f"unknown case: {body.case_id}")
    return {"session_id": sessions.create(body.case_id)}


@app.post("/api/sessions/{session_id}/load")
def load(session_id: str):
    if not sessions.exists(session_id):
        raise HTTPException(404, "unknown session")
    return StreamingResponse(stream_load(session_id), media_type="text/event-stream")


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    if (s := sessions.state(session_id)) is None:
        raise HTTPException(404, "unknown session")
    return s


def reviewable(sid: str) -> dict:
    """The session's raw dict, or 404/409 when it cannot take review operations."""
    if (s := sessions.get(sid)) is None:
        raise HTTPException(404, "unknown session")
    if s["load_running"]:
        raise HTTPException(409, "load running")
    if s["draft"] is None:
        raise HTTPException(409, "no draft")
    return s


@app.post("/api/sessions/{session_id}/ask")
def ask_question(session_id: str, body: Ask):
    s = reviewable(session_id)
    try:
        r = ask(body.question, s["draft"], s["spans"], s["events"], thread_id=s["chat_thread_id"])
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    return {"intent": r["intent"], "answer": r["answer"], "cited": r["cited"]}


@app.post("/api/sessions/{session_id}/corrections", status_code=201)
def propose_correction(session_id: str, body: Propose):
    with sessions.lock:
        s = reviewable(session_id)
        if not any(c.claim_id == body.claim_id for c in s["draft"].claims):
            raise HTTPException(404, f"unknown claim: {body.claim_id}")
        if s["pending"]:
            raise HTTPException(409, "correction pending")
        rev, clar = propose(s["draft"], body.claim_id, body.after, body.statement, len(s["revisions"]) + 1)
        sessions.update(session_id, pending=(rev, clar))
    return {"revision": rev.model_dump(mode="json"), "clarification": clar.model_dump(mode="json")}


def resolve(session_id: str, revision_id: str, status: str):
    with sessions.lock:
        s = reviewable(session_id)
        if not s["pending"] or s["pending"][0].revision_id != revision_id:
            raise HTTPException(404, "no such pending correction")
        rev, clar = (x.model_copy(update={"status": status}) for x in s["pending"])
        sessions.update(session_id, pending=None, revisions=[*s["revisions"], rev], clarifications=[*s["clarifications"], clar],
                        draft=accept(s["draft"], rev) if status == "accepted" else s["draft"])
        return sessions.state(session_id)


@app.post("/api/sessions/{session_id}/corrections/{revision_id}/accept")
def accept_correction(session_id: str, revision_id: str):
    return resolve(session_id, revision_id, "accepted")


@app.post("/api/sessions/{session_id}/corrections/{revision_id}/reject")
def reject_correction(session_id: str, revision_id: str):
    return resolve(session_id, revision_id, "rejected")


@app.post("/api/sessions/{session_id}/approve")
def approve(session_id: str, body: Approve):
    with sessions.lock:
        s = reviewable(session_id)
        if s["pending"]:
            raise HTTPException(409, "correction pending")
        sessions.update(session_id, draft=s["draft"].model_copy(
            update={"status": "approved", "approved_at": datetime.now(), "reviewer": body.reviewer}))
        return sessions.state(session_id)


@app.get("/api/sessions/{session_id}/export")
def export(session_id: str):
    s = reviewable(session_id)
    if s["draft"].status != "approved":
        raise HTTPException(409, "not approved")
    md = to_markdown(s["draft"], s["spans"], s["documents"], case_id=s["case_id"], clarifications=s["clarifications"])
    return Response(md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="discharge_summary_{s["case_id"]}.md"'})


class SinglePageApplicationFiles(StaticFiles):
    """Serve built files; any other non-API path gets index.html (client routes)."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith("api/"):
                raise
            return await super().get_response("index.html", scope)


if UI_DIR.is_dir():  # registered last so API routes win
    app.mount("/", SinglePageApplicationFiles(directory=UI_DIR, html=True), name="ui")
