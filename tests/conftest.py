"""Live tests share one model run of case_001 (the full load graph) per pytest session."""
import copy
import queue
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.streaming
from api import sessions

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def case001():
    """Runs case_001 through the load graph as the API does; keeps the SSE events it emitted."""
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(ROOT)
        sid = sessions.create("case_001")
        q: queue.Queue = queue.Queue()
        t0 = time.monotonic()
        api.streaming.run_load(sid, q)
        seconds = time.monotonic() - t0
    sse = []
    while (item := q.get()) is not api.streaming.DONE:
        sse.append(item)
    print(f"\ncase_001 load wall time: {seconds:.1f} s")
    assert sse[-1][0] == "done", sse[-1]
    s, last = sessions.get(sid), dict(sse)
    return SimpleNamespace(docs=s["documents"], spans=s["spans"], events=s["events"],
                           extract_warnings=last["extraction_done"]["warnings"], draft=s["draft"],
                           summary_warnings=last["draft"]["warnings"], sse=sse, load_seconds=seconds)


@pytest.fixture
def case_copy(case001):
    """A fresh copy per test, so no test sees another test's changes."""
    return copy.deepcopy(case001)


@pytest.fixture(autouse=True)
def reuse_case_in_app(request, monkeypatch):
    """Live tests: the app's load replays the session's model run instead of calling the model again."""
    if not request.node.get_closest_marker("live"):
        return  # non-live tests never load the case
    c = copy.deepcopy(request.getfixturevalue("case001"))

    def replay(sid, events):
        sessions.update(sid, documents=c.docs, spans=c.spans, events=c.events, draft=c.draft, load_running=False)
        for item in c.sse:
            events.put(item)
        events.put(api.streaming.DONE)
    monkeypatch.setattr(api.streaming, "run_load", replay)
