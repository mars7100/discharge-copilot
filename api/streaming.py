"""Worker thread -> queue -> async generator of SSE blocks (pattern of allec-rag src/api/streaming.py)."""
import asyncio
import json
import queue
import threading
import uuid
from pathlib import Path

from api import sessions
from core.ingest import ingest_dir
from langgraph.types import Command

from core.load_graph import load_graph
from core.models import TEMPLATE
from core.export import marker

FIXTURES = Path(__file__).parent.parent / "fixtures"
DONE = object()


def sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def conflict_payload(sid: str, conflicts) -> list[dict]:
    s = sessions.get(sid)
    docs = {d.document_id: d for d in s["documents"]}

    def quote(q):
        sp, d = s["spans"][q.span_id], docs[s["spans"][q.span_id].document_id]
        return {"span_id": q.span_id, "quote": q.quote, "document_id": sp.document_id, "filename": sp.filename,
                "date": d.date, "hospital_day": d.hospital_day, "marker": marker(sp), "text": sp.text}
    return [{"conflict_id": c.conflict_id, "description": c.description, "quotes": [quote(q) for q in c.quotes]} for c in conflicts]


def run_load(sid: str, events: queue.Queue) -> None:
    """Blocking load; puts (name, data) on the queue, then DONE."""
    try:
        docs, spans, _ = ingest_dir(FIXTURES / sessions.case_id(sid))
        sessions.update(sid, documents=docs, spans=spans)
        drive(sid, events, {"documents": docs, "spans": spans})
    except Exception as e:
        finish(sid, events, ("error", {"detail": f"{type(e).__name__}: {e}"}))


def run_resume(sid: str, events: queue.Queue, answers: list[dict]) -> None:
    try:
        drive(sid, events, Command(resume=answers))
    except Exception as e:
        finish(sid, events, ("error", {"detail": f"{type(e).__name__}: {e}"}))


def finish(sid: str, events: queue.Queue, last: tuple) -> None:
    """load_running is cleared before the last event."""
    sessions.update(sid, load_running=False, paused=False)
    events.put(last)
    events.put(DONE)


def drive(sid: str, events: queue.Queue, graph_input) -> None:
    config = {"configurable": {"thread_id": sessions.get(sid)["load_thread_id"]}}
    for u in load_graph.stream(graph_input, config, stream_mode="updates"):
        if "extract_note" in u:
            n = u["extract_note"]["notes"][0]
            if "detail" in n:
                events.put(("note_failed", {"document_id": n["document_id"], "detail": n["detail"]}))
            else:
                events.put(("note_extracted", {"document_id": n["document_id"], "event_count": len(n["events"]),
                                               "warnings": n["warnings"]}))
        elif "merge" in u:
            m = u["merge"]
            sessions.update(sid, events=m["events"])
            events.put(("extraction_done", {"event_count": len(m["events"]), "warnings": m["extract_warnings"],
                                            "conflict_count": len(m["discrepancies"])}))
        elif "__interrupt__" in u:
            conflicts = conflict_payload(sid, u["__interrupt__"][0].value)
            sessions.update(sid, conflicts=conflicts, paused=True)  # load_running stays true: editing stays locked
            events.put(("conflicts_found", {"conflicts": conflicts}))
            events.put(DONE)
            return
        elif "normalize" in u:
            sessions.update(sid, events=u["normalize"]["events"])
        elif "resolve" in u:
            sessions.update(sid, resolutions=u["resolve"]["resolutions"])
        elif "draft_section" in u:
            r = u["draft_section"]["sections"][0]
            if not r["documented"] and next(t for t in TEMPLATE if t["section_id"] == r["section_id"])["optional"]:
                events.put(("section_omitted", {"section_id": r["section_id"]}))
            else:
                events.put(("section_drafted", {"section_id": r["section_id"], "problem": r["problem"], "warnings": r["warnings"],
                                                "claims": [c.model_dump(include={"section", "text", "evidence_span_ids"}) for c in r["claims"]]}))
        elif "draft" in u:
            u = u["draft"]
            sessions.update(sid, draft=u["draft"])
            events.put(("dedupe_applied", {"count": len(u["removed"]),
                                           "removed": [c.model_dump(include={"section", "problem", "text"}) for c in u["removed"]]}))
            events.put(("draft", {"draft": u["draft"].model_dump(mode="json"), "warnings": u["draft_warnings"]}))
    finish(sid, events, ("done", {}))


def stream_load(sid: str):
    """Marks the load running and starts the worker now (it outlives a disconnect); returns the SSE generator."""
    sessions.update(sid, load_running=True, events=[], draft=None, revisions=[], clarifications=[], pending=None,
                    conflicts=[], resolutions=[], paused=False, load_thread_id=str(uuid.uuid4()))
    return start(run_load, sid)


def start(target, sid: str, *args):
    events: queue.Queue = queue.Queue()
    threading.Thread(target=target, args=(sid, events, *args)).start()

    async def drain():
        while (item := await asyncio.to_thread(events.get)) is not DONE:
            yield sse(*item)
    return drain()
