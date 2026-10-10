"""Live tests share one model run of case_001 (the full load graph) per pytest session."""
import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.streaming
from api import sessions

ROOT = Path(__file__).parent.parent


CLARIFICATION = "Medication A 5 mg initially, 10 mg from Day 3"


def _sse(response) -> list[tuple[str, dict]]:
    assert response.status_code == 200, response.read()
    out = []
    for block in "".join(response.iter_text()).strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((fields["event"], json.loads(fields["data"])))
    return out


@pytest.fixture(scope="session")
def case001():
    """Loads case_001 through the API; a pause is resumed by clarifying each conflict (ticket 07). Keeps the SSE."""
    from fastapi.testclient import TestClient

    from api.app import app
    import core.llm
    real, dedupe_calls = core.llm.parse, []

    def spy(schema, messages, timeout):  # ticket 10: keeps each real dedupe call's schema and output
        out = real(schema, messages, timeout)
        if "drop_claim_ids" in schema.model_fields:
            dedupe_calls.append((schema, out))
        return out
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(ROOT)
        mp.setattr(core.llm, "parse", spy)
        client = TestClient(app)
        sid = client.post("/api/sessions", json={"case_id": "case_001"}).json()["session_id"]
        t0 = time.monotonic()
        with client.stream("POST", f"/api/sessions/{sid}/load") as r:
            load_sse = _sse(r)
        resume_sse = []
        if load_sse[-1][0] == "conflicts_found":
            body = {"resolutions": [{"conflict_id": c["conflict_id"], "chosen_span_id": None, "clarification": CLARIFICATION}
                                    for c in load_sse[-1][1]["conflicts"]]}
            with client.stream("POST", f"/api/sessions/{sid}/resolutions", json=body) as r:
                resume_sse = _sse(r)
        seconds = time.monotonic() - t0
    sse = load_sse + resume_sse
    print(f"\ncase_001 load wall time: {seconds:.1f} s")
    assert sse[-1][0] == "done", sse[-1]
    s, last = sessions.get(sid), dict(sse)
    return SimpleNamespace(docs=s["documents"], spans=s["spans"], events=s["events"],
                           extract_warnings=last["extraction_done"]["warnings"], draft=s["draft"],
                           summary_warnings=last["draft"]["warnings"], sse=sse, load_sse=load_sse,
                           conflicts=s["conflicts"], resolutions=s["resolutions"], load_seconds=seconds,
                           dedupe_calls=dedupe_calls)


@pytest.fixture
def case_copy(case001):
    """A fresh copy per test, so no test sees another test's changes."""
    return copy.deepcopy(case001)


@pytest.fixture(autouse=True)
def reuse_case_in_app(request, monkeypatch):
    """Live tests: the app's load replays the session's model run (load, then resume) instead of calling the model again."""
    if not request.node.get_closest_marker("live"):
        return  # non-live tests never load the case
    c = copy.deepcopy(request.getfixturevalue("case001"))

    def replay(sid, events):
        sessions.update(sid, documents=c.docs, spans=c.spans, events=c.events, draft=c.draft, conflicts=c.conflicts,
                        resolutions=c.resolutions, paused=False, load_running=False)
        for item in c.sse:
            events.put(item)
        events.put(api.streaming.DONE)
    monkeypatch.setattr(api.streaming, "run_load", replay)
