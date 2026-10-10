"""Specification tests for the FastAPI backend (ticket 03a): through TestClient, model stubbed at core.llm.parse."""
import json
import re
import threading
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import llm
from core.export import marker
from core.extract import ExtractionResult
from core.ingest import ingest_dir
from core.models import ClinicalEvent, EvidenceRef
from tests.section_stub import EVERY_SECTION, IDS, SECTION_EVENTS, collapse, dedupe_result, kind, normalization, section_of, section_result

ROOT = Path(__file__).parent.parent
SPAN_LINE = re.compile(r"^\[(\S+)\] (.+)$", re.M)  # "[span_id] text" lines of the extraction prompt


def fake_parse(schema, messages, timeout):
    """One event quoting the case's second span verbatim; one claim citing that event's span."""
    user = next(m["content"] for m in messages if m["role"] == "user")
    if schema is ExtractionResult:
        sid, text = SPAN_LINE.findall(user)[1]
        return ExtractionResult(events=[ClinicalEvent(
            event_id="x", date_or_hospital_day="Hospital Day 1", category="presentation", statement=text,
            evidence=[EvidenceRef(span_id=sid, quote=text)], problem="Pneumonia",
            sections=EVERY_SECTION)])  # ticket 12: routed to every section, as before
    if kind(schema) == "dedupe":  # ticket 10: nothing to drop
        return dedupe_result(schema)
    if kind(schema) == "normalize":  # ticket 09: the one label maps onto itself
        return normalization(schema, [("Pneumonia", ["Pneumonia"], [])])
    if kind(schema) == "conflict":  # conflict check (ticket 06; schema is the implementer's): no conflicts
        return schema.model_validate({n: [] for n, f in schema.model_fields.items() if f.is_required()})
    if section_of(messages) != "reason_for_admission":  # ticket 08: one call per section; only this one documented
        return section_result(schema, False)
    sid = re.search(r"spans: (\w+)", user).group(1)
    return section_result(schema, True, [{"section": "reason_for_admission", "text": "Admitted.", "evidence_span_ids": [sid]}])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.chdir(ROOT)
    from api.app import app
    return TestClient(app)


@pytest.fixture
def calls(monkeypatch):
    """Stubs the model boundary; records the schema of every call. Set calls.fail to make every call raise."""
    class Calls(list):
        fail = False  # True: every call raises; a schema: only calls with that schema raise
        during = None  # optional callback run inside each model call
    rec = Calls()

    def parse(schema, messages, timeout):
        rec.append(schema)
        if rec.during:
            rec.during()
        if rec.fail is True or rec.fail is schema:
            raise RuntimeError("boom")
        return fake_parse(schema, messages, timeout)

    monkeypatch.setattr(llm, "parse", parse)
    return rec


def create(client, case_id="case_001"):
    r = client.post("/api/sessions", json={"case_id": case_id})
    assert r.status_code == 201
    return r.json()["session_id"]


def load(client, sid):
    """Returns the SSE stream as [(event, data)]."""
    with client.stream("POST", f"/api/sessions/{sid}/load") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((fields["event"], json.loads(fields["data"])))
    return out


NOTES = 6  # case_001 and case_002 have six notes each


def names(events):
    """Event names with the per-note events (ticket 06: one per note, any order) collapsed into one "per_note" entry."""
    out = [n for n, _ in events if n not in ("note_extracted", "note_failed")]
    per_note = [n for n, _ in events if n in ("note_extracted", "note_failed")]
    assert [n for n, _ in events][:len(per_note)] == per_note, "per-note events must come first"
    return (["per_note"] if len(per_note) == NOTES else per_note) + collapse(out)  # ticket 08: section events -> "sections"


def state(client, sid):
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    return r.json()


def test_list_cases_returns_fixture_directories_sorted(client):
    r = client.get("/api/cases")
    assert r.status_code == 200
    assert r.json() == {"cases": ["case_001", "case_002", "case_003"]}  # files and dot-dirs (.claude) excluded


def test_create_session_unknown_case_404(client):
    assert client.post("/api/sessions", json={"case_id": "no_such_case"}).status_code == 404


def test_new_session_state_is_empty(client):
    sid = create(client)
    s = state(client, sid)
    assert s["session_id"] == sid and s["case_id"] == "case_001"
    assert s["documents"] == [] and s["passages"] == {} and s["events"] == []
    assert s["draft"] is None and s["load_running"] is False
    uuid.UUID(s["chat_thread_id"])


def test_unknown_session_404_on_load_and_get(client):
    assert client.post("/api/sessions/nope/load").status_code == 404
    assert client.get("/api/sessions/nope").status_code == 404


def test_load_streams_extraction_draft_done_and_fills_state(client, calls):
    sid = create(client)
    thread_id = state(client, sid)["chat_thread_id"]
    events = load(client, sid)

    assert names(events) == ["per_note", "extraction_done", "sections", "dedupe_applied", "draft", "done"]
    (_, extracted), (_, drafted), (_, done) = events[NOTES], events[-2], events[-1]  # section events between (ticket 08)
    assert extracted == {"event_count": NOTES, "warnings": [], "conflict_count": 0}
    assert drafted["warnings"] == [] and done == {}
    # every model call went through core.llm.parse: one extraction per note, one conflict check, then the draft
    # ticket 08: then one draft call per template section; ticket 09: plus one normalization call, before drafting
    # (every event has the one problem, so hospital_course is one call)
    assert calls.count(ExtractionResult) == NOTES and len(calls) == NOTES + 2 + len(IDS)
    assert [kind(c) for c in calls].count("normalize") == 1
    assert all(kind(c) == "summary" for c in calls[-len(IDS):])

    docs, spans, _ = ingest_dir(ROOT / "fixtures" / "case_001")
    s = state(client, sid)
    assert s["load_running"] is False and s["chat_thread_id"] == thread_id
    assert [d["document_id"] for d in s["documents"]] == [d.document_id for d in docs]
    assert s["passages"] == {sid_: {"text": sp.text, "document_id": sp.document_id, "filename": sp.filename,
                                    "page": sp.page, "marker": marker(sp)} for sid_, sp in spans.items()}
    assert len(s["events"]) == NOTES and all(e["evidence"][0]["span_id"] in spans for e in s["events"])
    assert s["draft"] == drafted["draft"]
    cited = s["draft"]["claims"][0]["evidence_span_ids"]
    assert cited and all(c in s["passages"] for c in cited)  # citations resolve through passages


def test_load_running_true_during_load(client, calls):
    sid = create(client)
    seen = []

    def peek():  # GET from another thread, so a store lock held across the load fails instead of hanging
        t = threading.Thread(target=lambda: seen.append(client.get(f"/api/sessions/{sid}").json()["load_running"]))
        t.start()
        t.join(5)
    calls.during = peek
    load(client, sid)
    assert seen and all(seen)
    assert state(client, sid)["load_running"] is False


def test_error_streams_one_error_event_and_session_is_reusable(client, calls):
    sid = create(client)
    thread_id = state(client, sid)["chat_thread_id"]
    assert names(load(client, sid)) == ["per_note", "extraction_done", "sections", "dedupe_applied", "draft", "done"]

    calls.fail = ExtractionResult  # every note fails; the conflict check succeeds
    events = load(client, sid)
    assert names(events) == ["per_note", "error"]
    assert events[-1][1]["detail"].startswith("ExtractionError: ")
    s = state(client, sid)
    assert s["load_running"] is False
    assert s["events"] == [] and s["draft"] is None  # stale results cleared on retry
    assert s["session_id"] == sid and s["chat_thread_id"] == thread_id

    calls.fail = False
    assert names(load(client, sid)) == ["per_note", "extraction_done", "sections", "dedupe_applied", "draft", "done"]
    s = state(client, sid)
    assert len(s["events"]) == NOTES and s["draft"] is not None and s["chat_thread_id"] == thread_id


def test_error_in_draft_step_streams_error_without_done(client, calls):
    sid = create(client)
    calls.during = lambda: setattr(calls, "fail", kind(calls[-1]) == "summary")
    events = load(client, sid)
    assert names(events) == ["per_note", "extraction_done", "error"]
    assert events[-1][1]["detail"].startswith("SummaryError: ")
    assert state(client, sid)["load_running"] is False


def test_client_disconnect_mid_stream_still_lands_results(client, calls):
    sid = create(client)
    with client.stream("POST", f"/api/sessions/{sid}/load") as r:
        next(r.iter_text())
    deadline = time.time() + 5
    while state(client, sid)["load_running"] and time.time() < deadline:
        time.sleep(0.05)
    s = state(client, sid)
    assert s["load_running"] is False and s["draft"] is not None


def snapshot(s):
    return s["documents"], s["passages"], s["events"], s["draft"]


@pytest.mark.parametrize("concurrent", [False, True])
def test_sessions_on_different_cases_are_isolated(client, calls, concurrent):
    a, b = create(client, "case_001"), create(client, "case_002")
    if concurrent:
        threads = [threading.Thread(target=load, args=(TestClient(client.app), s)) for s in (a, b)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
    else:
        load(client, a)
        load(client, b)
    sa, sb = state(client, a), state(client, b)
    for s, case in ((sa, "case_001"), (sb, "case_002")):
        _, spans, _ = ingest_dir(ROOT / "fixtures" / case)
        assert s["case_id"] == case and s["load_running"] is False
        assert {k: v["text"] for k, v in s["passages"].items()} == {k: sp.text for k, sp in spans.items()}
        quote = s["events"][0]["evidence"][0]
        assert quote["quote"] in spans[quote["span_id"]].text
    assert snapshot(sa) != snapshot(sb) and sa["events"] != sb["events"]
    assert sa["chat_thread_id"] != sb["chat_thread_id"]


@pytest.mark.live
def test_case_001_live_load(client):
    sid = create(client)
    events = load(client, sid)
    # ticket 07: case_001 pauses on its conflict; the replayed run includes the resume stream after conflicts_found
    # ticket 09: hospital_course streams one section event per problem, so collapse any run of section events
    ns = names(events)
    live = ["sections" if n in SECTION_EVENTS else n for i, n in enumerate(ns) if not (n in SECTION_EVENTS and i and ns[i - 1] in SECTION_EVENTS)]
    assert live == ["per_note", "extraction_done", "conflicts_found", "sections", "dedupe_applied", "draft", "done"], events
    s = state(client, sid)
    assert len(s["events"]) >= 3 and s["draft"]["claims"]
    assert all(c in s["passages"] for claim in s["draft"]["claims"] for c in claim["evidence_span_ids"])
