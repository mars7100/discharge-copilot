import json
import os
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import sessions
from api.schemas import Approve, Ask, CreateSession, Propose, Resolve
from api.streaming import FIXTURES, run_resume, sse, start, stream_load
from core.export import to_docx, to_markdown
from core.review_graph import ask, ask_stream
from core.revise import accept, propose, rewrite

app = FastAPI()
UI_DIR = Path(os.environ.get("DISCHARGE_UI_DIR", Path(__file__).parent.parent / "frontend" / "dist"))
TEMPLATE = Path(__file__).parent.parent / "core" / "template.json"
ASK_RUNNING: set[str] = set()  # guarded by sessions.lock; JSON and streamed asks share history


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


@app.post("/api/sessions/{session_id}/resolutions")
def resolve_conflicts(session_id: str, body: Resolve):
    with sessions.lock:  # check and un-pause together: a second submit sees "not paused"
        if (s := sessions.get(session_id)) is None:
            raise HTTPException(404, "unknown session")
        if not s["paused"]:
            raise HTTPException(409, "not paused")
        quoted = {c["conflict_id"]: {q["span_id"] for q in c["quotes"]} for c in s["conflicts"]}
        ids = [r.conflict_id for r in body.resolutions]
        if sorted(ids) != sorted(quoted):
            raise HTTPException(422, "resolve each conflict exactly once")
        for r in body.resolutions:
            if (r.chosen_span_id is None) == (r.clarification is None):
                raise HTTPException(422, f"{r.conflict_id}: give a chosen span or a clarification, not both or neither")
            if r.chosen_span_id is not None and r.chosen_span_id not in quoted[r.conflict_id]:
                raise HTTPException(422, f"{r.conflict_id}: chosen span is not one of its quotes")
            if r.clarification is not None and not r.clarification.strip():
                raise HTTPException(422, f"{r.conflict_id}: blank clarification")
        sessions.update(session_id, paused=False)
        stream = start(run_resume, session_id, [r.model_dump() for r in body.resolutions])
    return StreamingResponse(stream, media_type="text/event-stream")


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
    s = begin_ask(session_id)
    try:
        r = ask(body.question, s["draft"], s["spans"], s["events"], thread_id=s["chat_thread_id"])
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    finally:
        with sessions.lock:
            ASK_RUNNING.discard(session_id)
    return {"intent": r["intent"], "answer": r["answer"], "cited": r["cited"]}


def begin_ask(session_id: str) -> dict:
    """Reserve one review conversation without holding the store lock during model I/O."""
    with sessions.lock:
        s = reviewable(session_id)
        if session_id in ASK_RUNNING:
            raise HTTPException(409, "ask running")
        ASK_RUNNING.add(session_id)
        return s


@app.post("/api/sessions/{session_id}/ask/stream")
async def stream_question(session_id: str, body: Ask, request: Request) -> StreamingResponse:
    """Return incremental SSE review events and close model I/O on disconnect."""
    s = begin_ask(session_id)

    async def drain() -> AsyncIterator[str]:
        """Encode events, releasing the conversation reservation on every exit."""
        try:
            async with aclosing(ask_stream(body.question, s["draft"], s["spans"], s["events"],
                                          thread_id=s["chat_thread_id"])) as stream:
                async for name, data in stream:
                    if await request.is_disconnected():
                        return
                    yield sse(name, data)
        except Exception as e:
            yield sse("error", {"detail": f"{type(e).__name__}: {e}"})
        finally:
            with sessions.lock:
                ASK_RUNNING.discard(session_id)

    return StreamingResponse(drain(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/sessions/{session_id}/corrections", status_code=201)
def propose_correction(session_id: str, body: Propose):
    if not body.statement.strip():
        raise HTTPException(422, "blank statement")
    with sessions.lock:
        s = reviewable(session_id)
        claim = next((c for c in s["draft"].claims if c.claim_id == body.claim_id), None)
        if claim is None:
            raise HTTPException(404, f"unknown claim: {body.claim_id}")
        if s["pending"]:
            raise HTTPException(409, "correction pending")
        draft, spans = s["draft"], s["spans"]
    try:  # lock released: the model call is slow
        after = rewrite(claim, spans, body.statement)
    except Exception as e:
        raise HTTPException(502, f"correction failed: {type(e).__name__}: {e}")
    if after is None:
        raise HTTPException(422, "the statement did not change the claim")
    with sessions.lock:
        s = reviewable(session_id)
        if s["draft"] is not draft or s["pending"]:
            raise HTTPException(409, "session changed during the proposal")
        rev, clar = propose(draft, body.claim_id, after, body.statement, len(s["revisions"]) + 1)
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
def export(session_id: str, format: Literal["markdown", "docx"] = "markdown") -> Response:
    """Download an approved summary in the requested document format."""
    s = reviewable(session_id)
    if s["draft"].status != "approved":
        raise HTTPException(409, "not approved")
    render = to_docx if format == "docx" else to_markdown
    content = render(s["draft"], s["spans"], s["documents"], case_id=s["case_id"], clarifications=s["clarifications"], resolutions=s["resolutions"],
                      missing_notes=s["missing_notes"])
    extension = "docx" if format == "docx" else "md"
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if format == "docx" else "text/markdown"
    return Response(content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="discharge_summary_{s["case_id"]}.{extension}"'})


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
