import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import sessions
from api.schemas import CreateSession
from api.streaming import FIXTURES, stream_load

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
