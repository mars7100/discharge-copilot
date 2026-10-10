"""Worker thread -> queue -> async generator of SSE blocks (pattern of allec-rag src/api/streaming.py)."""
import asyncio
import json
import queue
import threading
from pathlib import Path

from api import sessions
from core.ingest import ingest_dir
from core.load_graph import load_graph

FIXTURES = Path(__file__).parent.parent / "fixtures"
DONE = object()


def sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def run_load(sid: str, events: queue.Queue) -> None:
    """Blocking load; puts (name, data) on the queue, then DONE. load_running is cleared before the last event."""
    try:
        docs, spans, _ = ingest_dir(FIXTURES / sessions.case_id(sid))
        sessions.update(sid, documents=docs, spans=spans)
        for u in load_graph.stream({"documents": docs, "spans": spans}, stream_mode="updates"):
            if "extract" in u:
                sessions.update(sid, events=u["extract"]["events"])
                events.put(("extraction_done", {"event_count": len(u["extract"]["events"]),
                                                "warnings": u["extract"]["extract_warnings"]}))
            elif "draft" in u:
                sessions.update(sid, draft=u["draft"]["draft"])
                events.put(("draft", {"draft": u["draft"]["draft"].model_dump(mode="json"),
                                      "warnings": u["draft"]["draft_warnings"]}))
        last = ("done", {})
    except Exception as e:
        last = ("error", {"detail": f"{type(e).__name__}: {e}"})
    sessions.update(sid, load_running=False)
    events.put(last)
    events.put(DONE)


def stream_load(sid: str):
    """Marks the load running and starts the worker now (it outlives a disconnect); returns the SSE generator."""
    sessions.update(sid, load_running=True, events=[], draft=None)
    events: queue.Queue = queue.Queue()
    threading.Thread(target=run_load, args=(sid, events)).start()

    async def drain():
        while (item := await asyncio.to_thread(events.get)) is not DONE:
            yield sse(*item)
    return drain()
