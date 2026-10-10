"""Specification tests for ticket 06 (parallel per-note extraction + conflict check), see issues/06-contract.md.

Seams: core.load_graph.load_graph.stream, core.extract.extract_events, the HTTP API through TestClient.
The model is stubbed only at core.llm.parse and dispatches on schema: ExtractionResult -> per-note extraction,
SummaryResult -> drafting, any other schema -> the conflict check. The conflict check's result schema is the
implementer's choice; the stub fills whichever of its fields is annotated list[ConflictItem].
"""
import json
import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import llm
from core.extract import ExtractionResult, extract_events
from core.ingest import ingest_dir
from core.load_graph import load_graph
from core.models import ClinicalEvent, Document, Draft, SourceSpan, SummaryClaim
from core.summarize import SummaryResult

ROOT = Path(__file__).parent.parent
SPAN_ID = re.compile(r"note_\d+_p\d+_b\d+")
PROBLEM = "community-acquired pneumonia"
WAIT = 5  # seconds; an upper bound on blocking waits, never a sleep


def note_events(passages: list[SourceSpan]) -> list[ClinicalEvent]:
    """Model output for one note, deliberately not in passage order:
    A cites passage 3; B cites passages 4 and 1; C cites passage 1. Merged order must be B, C, A
    (smallest cited passage order first, then the model's index). A is flagged needs_review by the model."""
    doc = passages[0].document_id

    def ev(label, *refs, **kw):
        return ClinicalEvent(event_id="x", date_or_hospital_day="Hospital Day 1", category="other",
                             statement=f"{doc}:{label}", problem=PROBLEM,
                             evidence=[{"span_id": r.span_id, "quote": r.text} for r in refs], **kw)
    p = passages
    return [ev("A", p[2], needs_review=True), ev("B", p[3], p[0]), ev("C", p[0])]


def conflict_result(schema, items):
    """items: [(description, [(span_id, quote), ...])]."""
    from core.models import ConflictItem  # contract type (ticket 06)
    fields = [n for n, f in schema.model_fields.items() if f.annotation == list[ConflictItem]]
    assert fields, f"conflict-check schema {schema.__name__} has no list[ConflictItem] field"
    return schema(**{fields[0]: [ConflictItem(conflict_id="x", description=d,
                                              quotes=[{"span_id": s, "quote": q} for s, q in quotes])
                                 for d, quotes in items]})


class Model:
    """Stub for core.llm.parse. calls: (kind, document_ids, span_ids seen, messages copy) per call."""

    def __init__(self, spans: dict[str, SourceSpan]):
        self.spans = spans
        self.calls = []
        self.lock = threading.Lock()
        self.conflicts = lambda attempt: []  # attempt 1, 2, ... -> items for conflict_result
        self.fail = set()  # document IDs whose extraction raises; "conflict" makes the conflict check raise
        self.on_extract = lambda doc: None  # runs inside each extraction call, per document seen
        self.on_conflict = lambda: None
        first = min(s.document_id for s in spans.values())
        self.claim_span = self.passages(first)[2].span_id  # cited by the needs_review-flagged event A

    def passages(self, doc):
        return sorted((s for s in self.spans.values() if s.document_id == doc), key=lambda s: s.order)

    def kind_calls(self, kind):
        return [c for c in self.calls if c[0] == kind]

    def __call__(self, schema, messages, timeout):
        seen = set(SPAN_ID.findall(json.dumps(messages))) & self.spans.keys()
        docs = sorted({self.spans[s].document_id for s in seen})
        kind = "extract" if schema is ExtractionResult else "summary" if schema is SummaryResult else "conflict"
        with self.lock:
            self.calls.append((kind, docs, seen, list(messages)))
            attempt = len(self.kind_calls(kind))
        if kind == "extract":
            for d in docs:
                self.on_extract(d)
            if self.fail & set(docs):
                raise RuntimeError("extraction boom")
            return ExtractionResult(events=[e for d in docs for e in note_events(self.passages(d))])
        if kind == "summary":
            return SummaryResult(claims=[SummaryClaim(claim_id="x", section="reason_for_admission", text="Admitted.",
                                                      evidence_span_ids=[self.claim_span], support_status="unverified")])
        self.on_conflict()
        if "conflict" in self.fail:
            raise RuntimeError("conflict boom")
        return conflict_result(schema, self.conflicts(attempt))


def synthetic(n):
    """n notes with 4 passages each."""
    docs = [Document(document_id=f"note_{k:02d}", filename=f"note_{k:02d}.txt", date=None, hospital_day=k,
                     type="Progress note", author_role=None) for k in range(1, n + 1)]
    spans = {f"note_{k:02d}_p01_b{j:02d}": SourceSpan(span_id=f"note_{k:02d}_p01_b{j:02d}", document_id=f"note_{k:02d}",
                                                      filename=f"note_{k:02d}.txt", page=1, order=j,
                                                      text=f"Note {k} passage {j} documents a finding.")
             for k in range(1, n + 1) for j in range(1, 5)}
    return docs, spans


def contains(x, cls):
    if isinstance(x, cls):
        return True
    if isinstance(x, dict):
        return any(contains(v, cls) for v in x.values())
    if isinstance(x, (list, tuple)):
        return any(contains(v, cls) for v in x)
    return False


def drafts(updates):
    return [v for u in updates for node in u.values() if isinstance(node, dict) for v in node.values() if isinstance(v, Draft)]


def stream(docs, spans):
    return load_graph.stream({"documents": docs, "spans": spans}, stream_mode="updates")


# ---------- graph seam ----------

def test_one_extraction_call_per_note_and_one_conflict_check_over_all_passages(monkeypatch):
    docs, spans = synthetic(3)
    model = Model(spans)
    monkeypatch.setattr(llm, "parse", model)
    updates = list(stream(docs, spans))

    extract = model.kind_calls("extract")
    assert sorted(c[1] for c in extract) == [[d.document_id] for d in docs]  # one call per note
    for _, (doc,), seen, _ in extract:
        assert seen == {s.span_id for s in model.passages(doc)}  # only that note's passages
    conflict = model.kind_calls("conflict")
    assert len(conflict) == 1 and conflict[0][2] == set(spans)  # one call over every passage
    assert len(drafts(updates)) == 1


def test_extraction_calls_run_concurrently(monkeypatch):
    docs, spans = synthetic(3)
    model = Model(spans)
    monkeypatch.setattr(llm, "parse", model)
    cv, live = threading.Condition(), {"now": 0, "max": 0}

    def hold(doc):  # blocks until two extraction calls have been in flight together
        with cv:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
            cv.notify_all()
            cv.wait_for(lambda: live["max"] >= 2, timeout=3)
            live["now"] -= 1
    model.on_extract = hold
    updates = list(stream(docs, spans))
    assert live["max"] >= 2
    assert len(drafts(updates)) == 1


def test_concurrency_never_exceeds_six_with_more_notes(monkeypatch):
    docs, spans = synthetic(8)
    model = Model(spans)
    monkeypatch.setattr(llm, "parse", model)
    cv, live = threading.Condition(), {"now": 0, "max": 0, "started": 0}

    def hold(doc):  # each call stays in flight until all 8 have started (or 1 s passes, as it must under a cap)
        with cv:
            live["now"] += 1
            live["started"] += 1
            live["max"] = max(live["max"], live["now"])
            cv.notify_all()
            cv.wait_for(lambda: live["started"] == len(docs), timeout=1)
            live["now"] -= 1
    model.on_extract = hold
    updates = list(stream(docs, spans))
    assert 2 <= live["max"] <= 6, live
    assert sorted(c[1] for c in model.kind_calls("extract")) == [[d.document_id] for d in docs]
    assert len(drafts(updates)) == 1


def test_a_finished_note_streams_before_other_branches_finish(monkeypatch):
    docs, spans = synthetic(3)
    model = Model(spans)
    monkeypatch.setattr(llm, "parse", model)
    release, timed_out = threading.Event(), []

    def block():
        if not release.wait(WAIT):
            timed_out.append(True)
    model.on_extract = lambda doc: doc == "note_03" and block()
    model.on_conflict = block
    updates = []
    for u in stream(docs, spans):  # note_03 and the conflict check are held until a note's events arrive
        updates.append(u)
        if contains(u, ClinicalEvent):
            release.set()
    assert not timed_out, "no per-note result was streamed while other branches were still running"
    assert len(drafts(updates)) == 1


# ---------- extraction ----------

def test_extract_events_keeps_problem_and_never_sets_needs_review(monkeypatch):
    docs, spans = synthetic(1)
    model = Model(spans)
    monkeypatch.setattr(llm, "parse", model)
    events, warnings = extract_events(docs, spans)
    assert len(events) == 3 and warnings == []
    assert [e.problem for e in events] == [PROBLEM] * 3
    assert not any(e.needs_review for e in events)  # the model flagged one; extraction no longer does


# ---------- HTTP API ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.chdir(ROOT)
    from api.app import app
    return TestClient(app)


@pytest.fixture
def case():
    docs, spans, _ = ingest_dir(ROOT / "fixtures" / "case_001")
    return [d.document_id for d in docs], spans


@pytest.fixture
def model(monkeypatch, case):
    m = Model(case[1])
    monkeypatch.setattr(llm, "parse", m)
    return m


def create(client):
    r = client.post("/api/sessions", json={"case_id": "case_001"})
    assert r.status_code == 201
    return r.json()["session_id"]


def load(client, sid):
    with client.stream("POST", f"/api/sessions/{sid}/load") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def state(client, sid):
    return client.get(f"/api/sessions/{sid}").json()


def expected_statements(ids):
    return [f"{d}:{x}" for d in ids for x in "BCA"]


def test_numbering_is_identical_for_different_completion_orders(client, model, case):
    ids, _ = case
    runs = []
    for order in (ids, ids[::-1]):
        done, late = {d: threading.Event() for d in ids}, []

        def gate(doc, order=order, done=done, late=late):  # note k finishes only after the note before it in `order`
            i = order.index(doc)
            if i and not late and not done[order[i - 1]].wait(WAIT):
                late.append(doc)
            done[doc].set()
        model.on_extract = gate
        sid = create(client)
        sse = load(client, sid)
        assert sse[-1][0] == "done", sse
        assert not late, f"completion order {order} could not be forced"
        runs.append([(e["event_id"], e["statement"], [r["span_id"] for r in e["evidence"]])
                     for e in state(client, sid)["events"]])

    assert [s for _, s, _ in runs[0]] == expected_statements(ids)  # note order, then passage order, then model index
    assert [i for i, _, _ in runs[0]] == [f"E{n:02d}" for n in range(1, 3 * len(ids) + 1)]
    assert runs[0] == runs[1]


def test_conflicts_become_discrepancies_and_sse_reports_each_note(client, model, case):
    ids, _ = case
    p = model.passages
    late = ("Dose differs between progress notes", [(s.span_id, s.text) for s in (p("note_04")[1], p("note_05")[0])])
    early = ("Route differs between early notes", [(s.span_id, s.text) for s in (p("note_02")[2], p("note_03")[0])])
    model.conflicts = lambda attempt: [late, early]
    sid = create(client)
    sse = load(client, sid)

    names = [n for n, _ in sse]
    assert names[len(ids):] == ["extraction_done", "draft", "done"]
    per_note = sse[:len(ids)]
    assert {n for n, _ in per_note} == {"note_extracted"}
    assert sorted(d["document_id"] for _, d in per_note) == sorted(ids)  # one per note
    assert all(d == {"document_id": d["document_id"], "event_count": 3, "warnings": []} for _, d in per_note)
    assert sse[len(ids)][1] == {"event_count": 3 * len(ids), "warnings": [], "conflict_count": 2}

    s = state(client, sid)
    assert [(d["discrepancy_id"], d["description"], sorted(d["source_span_ids"]), d["status"])
            for d in s["draft"]["discrepancies"]] == [
        ("D01", early[0], sorted(sid_ for sid_, _ in early[1]), "open"),  # numbered by first quote's note/passage
        ("D02", late[0], sorted(sid_ for sid_, _ in late[1]), "open")]
    assert s["draft"] == sse[len(ids) + 1][1]["draft"]
    assert [e["problem"] for e in s["events"]] == [PROBLEM] * 3 * len(ids)
    assert not any(e["needs_review"] for e in s["events"])
    assert not any(c["support_status"] == "needs_review" for c in s["draft"]["claims"])


def test_conflict_quotes_validated_with_one_retry(client, model, case):
    p = model.passages
    a, b, c, d = p("note_01")[0], p("note_02")[0], p("note_03")[0], p("note_04")[0]
    kept = ("Weight differs", [(a.span_id, a.text), (b.span_id, b.text), (c.span_id, "This sentence is not in the note.")])
    dropped = ("Allergy differs", [(d.span_id, d.text), ("note_09_p01_b01", "Penicillin allergy.")])
    model.conflicts = lambda attempt: [kept, dropped]  # same invalid output on the retry
    sid = create(client)
    sse = load(client, sid)
    assert sse[-1][0] == "done", sse

    calls = model.kind_calls("conflict")
    assert len(calls) == 2  # exactly one validation retry
    first, second = calls[0][3], calls[1][3]
    assert second[:len(first)] == first and len(second) > len(first)
    assert any(m["role"] != "assistant" and "note_09_p01_b01" in str(m["content"]) for m in second[len(first):])

    s = state(client, sid)
    assert [sorted(x["source_span_ids"]) for x in s["draft"]["discrepancies"]] == [sorted([a.span_id, b.span_id])]
    extraction_done = dict(sse)["extraction_done"]
    assert extraction_done["conflict_count"] == 1
    assert any("note_09_p01_b01" in w for w in extraction_done["warnings"])  # final errors become warnings


def test_one_note_failing_does_not_fail_the_load(client, model, case):
    ids, _ = case
    model.fail = {"note_03"}
    sid = create(client)
    sse = load(client, sid)

    names = [n for n, _ in sse]
    assert names[len(ids):] == ["extraction_done", "draft", "done"]
    per_note = {d["document_id"]: (n, d) for n, d in sse[:len(ids)]}
    assert sorted(per_note) == sorted(ids)
    name, failed = per_note.pop("note_03")
    assert name == "note_failed" and set(failed) == {"document_id", "detail"} and failed["detail"]
    assert all(n == "note_extracted" for n, _ in per_note.values())
    extraction_done = dict(sse)["extraction_done"]
    assert extraction_done["event_count"] == 3 * (len(ids) - 1)
    assert any("note_03" in w for w in extraction_done["warnings"])
    s = state(client, sid)
    assert [e["statement"] for e in s["events"]] == expected_statements([d for d in ids if d != "note_03"])
    assert s["load_running"] is False and s["draft"] is not None


@pytest.mark.parametrize("failing", ["all_notes", "conflict"])
def test_all_notes_or_conflict_check_failing_fails_the_load(client, model, case, failing):
    ids, _ = case
    model.fail = set(ids) if failing == "all_notes" else {"conflict"}
    sid = create(client)
    sse = load(client, sid)

    names = [n for n, _ in sse]
    assert names[-1] == "error" and sse[-1][1]["detail"]
    assert "draft" not in names and "done" not in names
    assert not model.kind_calls("summary")
    if failing == "conflict":
        assert len(model.kind_calls("conflict")) == 2  # failed after its own retry
    s = state(client, sid)
    assert s["load_running"] is False and s["draft"] is None
