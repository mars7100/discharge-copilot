"""In-memory session store. Nothing persisted."""
import threading
import uuid

from core.export import marker

lock = threading.RLock()  # reentrant: a review route holds it across its check and update
_sessions: dict[str, dict] = {}


def create(case_id: str) -> str:
    sid = str(uuid.uuid4())
    with lock:
        _sessions[sid] = {"session_id": sid, "case_id": case_id, "documents": [], "spans": {}, "events": [],
                          "draft": None, "chat_thread_id": str(uuid.uuid4()), "load_running": False,
                          "revisions": [], "clarifications": [], "pending": None,
                          "conflicts": [], "resolutions": [], "paused": False, "load_thread_id": None}
    return sid


def exists(sid: str) -> bool:
    with lock:
        return sid in _sessions


def case_id(sid: str) -> str:
    with lock:
        return _sessions[sid]["case_id"]


def get(sid: str) -> dict | None:
    with lock:
        return _sessions.get(sid)


def update(sid: str, **fields) -> None:
    with lock:
        _sessions[sid].update(fields)


def state(sid: str) -> dict | None:
    """JSON-ready snapshot, or None if unknown."""
    with lock:
        s = _sessions.get(sid)
        if s is None:
            return None
        return {**{k: v for k, v in s.items() if k != "spans"}, "documents": [d.model_dump(mode="json") for d in s["documents"]],
                "events": [e.model_dump(mode="json") for e in s["events"]],
                "draft": s["draft"] and s["draft"].model_dump(mode="json"),
                "resolutions": [r.model_dump(mode="json") for r in s["resolutions"]],
                "revisions": [r.model_dump(mode="json") for r in s["revisions"]],
                "clarifications": [c.model_dump(mode="json") for c in s["clarifications"]],
                "pending": s["pending"] and {"revision": s["pending"][0].model_dump(mode="json"),
                                             "clarification": s["pending"][1].model_dump(mode="json")},
                "passages": {k: {"text": sp.text, "document_id": sp.document_id, "filename": sp.filename,
                                 "page": sp.page, "marker": marker(sp)} for k, sp in s["spans"].items()}}
