from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from api import sessions
from api.schemas import CreateSession
from api.streaming import FIXTURES, stream_load

app = FastAPI()


@app.get("/api/cases")
def list_cases():
    return {"cases": sorted(p.name for p in FIXTURES.iterdir() if p.is_dir() and not p.name.startswith("."))}


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
