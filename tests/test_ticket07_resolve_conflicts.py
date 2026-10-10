"""Specification tests for ticket 07 (resolve conflicts before drafting), see issues/07-contract.md.

Seams: core.load_graph.load_graph.stream (with a thread_id config), core.summarize.generate_draft,
core.export.to_markdown, and the HTTP API (load + resolutions) through TestClient.
The model is stubbed only at core.llm.parse and dispatches on schema (extraction / summary / conflict check).
Resume is exercised through the API: the graph-level resume payload shape is the implementer's choice.
"""
import json
import re
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from core import llm
from core.export import marker, to_markdown
from core.extract import ExtractionResult
from core.ingest import ingest_dir
from core.load_graph import load_graph
from core.models import ClinicalEvent, Discrepancy, Draft, EvidenceRef, SummaryClaim
from core.summarize import SummaryResult, generate_draft
from tests.test_api import ROOT, client, create, state  # noqa: F401  (client is a fixture)
from tests.test_api_ticket04 import OPERATIONS, approve, asked, call  # noqa: F401  (asked is a fixture)
from tests.test_ticket06_parallel_load import conflict_result

PREFIX = "/api/sessions"
WAIT = 5
DESC = "Medication A dose differs between notes"
Q04 = ("note_04_p01_b07", "Medication A 10 mg daily.")            # "Current medications: Intravenous Antibiotic B. ..."
Q05 = ("note_05_p01_b04", "Medication A 5 mg given this shift.")  # "Medications: ... First dose of oral Antibiotic B given."
QUOTE_SPANS = {Q04[0], Q05[0]}
CLARIFICATION = "Medication A 5 mg initially, 10 mg from Day 3"
KEEP_SPAN = "note_02_p01_b02"
RESOLVED_LINE = re.compile(r"(D\d\d) \| RESOLVED \(clinician-provided\) \| (.+?) \| spans: (.+)")

DOCS, SPANS, _ = ingest_dir(ROOT / "fixtures" / "case_001")


def ev(statement, *refs):
    return ClinicalEvent(event_id="x", date_or_hospital_day="Hospital Day 3", category="treatment_documented",
                         statement=statement, evidence=[{"span_id": s, "quote": q} for s, q in refs])


def plain_span(doc, exclude=()):
    return next(s for s in sorted(SPANS.values(), key=lambda s: s.order)
                if s.document_id == doc and "\n" not in s.text and s.span_id not in exclude)


def events_for(doc):
    """KEEP events never overlap a conflict quote; DROP events do (and must never reach drafting)."""
    if doc == "note_04":
        return [ev("KEEP note_04 antibiotic route", (Q04[0], "Intravenous Antibiotic B.")),  # same span, no overlap
                ev("DROP note_04 medication dose", Q04)]
    if doc == "note_05":
        other = plain_span("note_05", exclude={Q05[0]})
        return [ev("KEEP note_05 antibiotic first dose", (Q05[0], "First dose of oral Antibiotic B given.")),
                ev("DROP note_05 medication dose", Q05),
                ev("DROP note_05 partly conflicting", (other.span_id, other.text), (Q05[0], "Medication A 5 mg"))]
    s = plain_span(doc)
    return [ev(f"KEEP {doc}", (s.span_id, s.text))]


class Model:
    """Stub for core.llm.parse. calls: (kind, messages) per call."""

    def __init__(self):
        self.calls, self.lock = [], threading.Lock()
        self.conflicts = [(DESC, [Q04, Q05])]
        self.carry = True              # summary claims carry each resolution listed in the prompt
        self.summary_fail = False
        self.on_summary = lambda: None

    def kind_calls(self, kind):
        return [m for k, m in self.calls if k == kind]

    def __call__(self, schema, messages, timeout):
        kind = "extract" if schema is ExtractionResult else "summary" if schema is SummaryResult else "conflict"
        with self.lock:
            self.calls.append((kind, [dict(m) for m in messages]))
        if kind == "extract":
            docs = sorted({SPANS[s].document_id for s in re.findall(r"note_\d+_p\d+_b\d+", json.dumps(messages))})
            return ExtractionResult(events=[e for d in docs for e in events_for(d)])
        if kind == "conflict":
            return conflict_result(schema, self.conflicts)
        self.on_summary()
        if self.summary_fail:
            raise RuntimeError("summary boom")
        claims = [SummaryClaim(claim_id="x", section="reason_for_admission", text="Admitted.",
                               evidence_span_ids=[KEEP_SPAN], support_status="unverified")]
        if self.carry:  # state each resolved fact as written, citing only its first span
            for rid, text, spans in RESOLVED_LINE.findall(text_of(messages)):
                claims.append(SummaryClaim(claim_id="x", section="hospital_course", text=text,
                                           evidence_span_ids=[re.findall(r"note_\d+_p\d+_b\d+", spans)[0]],
                                           clinician_clarification_ids=[rid], support_status="unverified"))
        return SummaryResult(claims=claims)


def text_of(messages):
    return "\n".join(str(m["content"]) for m in messages)


@pytest.fixture
def model(monkeypatch):
    m = Model()
    monkeypatch.setattr(llm, "parse", m)
    return m


def parse_sse(body):
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def load(client, sid):
    with client.stream("POST", f"{PREFIX}/{sid}/load") as r:
        assert r.status_code == 200
        return parse_sse("".join(r.iter_text()))


def submit(client, sid, resolutions):
    """POST resolutions; returns (status, SSE events or JSON body)."""
    with client.stream("POST", f"{PREFIX}/{sid}/resolutions", json={"resolutions": resolutions}) as r:
        body = "".join(r.iter_text())
        if r.status_code == 200:
            assert r.headers["content-type"].startswith("text/event-stream")
            return 200, parse_sse(body)
        return r.status_code, json.loads(body)


def pick(span_id, cid="D01"):
    return {"conflict_id": cid, "chosen_span_id": span_id, "clarification": None}


def clarify(text=CLARIFICATION, cid="D01"):
    return {"conflict_id": cid, "chosen_span_id": None, "clarification": text}


def paused(client, model):
    sid = create(client)
    sse = load(client, sid)
    assert sse[-1][0] == "conflicts_found", sse
    return sid


def resolution(text=CLARIFICATION, chosen=None):
    from core.models import Resolution  # contract type (ticket 07)
    return Resolution(conflict_id="D01", text=text, chosen_span_id=chosen, provenance="clinician-provided",
                      quotes=[EvidenceRef(span_id=s, quote=q, start=SPANS[s].text.index(q)) for s, q in (Q04, Q05)])


# ---------- graph seam ----------

def graph_updates(thread_id):
    return list(load_graph.stream({"documents": DOCS, "spans": SPANS},
                                  {"configurable": {"thread_id": thread_id}}, stream_mode="updates"))


def test_graph_pauses_before_drafting_when_conflicts_exist(model):
    updates = graph_updates(str(uuid.uuid4()))
    assert any("__interrupt__" in u for u in updates), [list(u) for u in updates]
    assert not any("draft" in u for u in updates)
    assert model.kind_calls("summary") == []  # nothing drafted before resolution


def test_graph_without_conflicts_drafts_without_pausing(model):
    model.conflicts = []
    updates = graph_updates(str(uuid.uuid4()))
    assert not any("__interrupt__" in u for u in updates)
    assert any("draft" in u for u in updates) and len(model.kind_calls("summary")) == 1


# ---------- load pauses ----------

def test_load_with_conflicts_ends_with_conflicts_found_and_drafts_nothing(client, model):
    sid = create(client)
    sse = load(client, sid)
    names = [n for n, _ in sse]
    assert names[-2:] == ["extraction_done", "conflicts_found"]
    assert "draft" not in names and "done" not in names
    assert model.kind_calls("summary") == []

    docs = {d.document_id: d for d in DOCS}
    quote = lambda s, q: {"span_id": s, "quote": q, "document_id": SPANS[s].document_id, "filename": SPANS[s].filename,
                          "date": docs[SPANS[s].document_id].date, "hospital_day": docs[SPANS[s].document_id].hospital_day,
                          "marker": marker(SPANS[s]), "text": SPANS[s].text}
    expected = [{"conflict_id": "D01", "description": DESC, "quotes": [quote(*Q04), quote(*Q05)]}]
    assert sse[-1][1] == {"conflicts": expected}

    s = state(client, sid)
    assert s["paused"] is True and s["load_running"] is True  # editing stays locked while paused
    assert s["conflicts"] == expected and s["resolutions"] == [] and s["draft"] is None
    assert s["load_thread_id"]


# ---------- resume ----------

@pytest.mark.parametrize("how", ["pick", "clarify"])
def test_resume_drafts_resolved_fact_with_both_citations(client, model, how):
    sid = paused(client, model)
    body = pick(Q05[0]) if how == "pick" else clarify()
    text = f"{DESC}: {Q05[1]}" if how == "pick" else CLARIFICATION
    status, sse = submit(client, sid, [body])
    assert status == 200
    assert [n for n, _ in sse] == ["draft", "done"], sse

    s = state(client, sid)
    assert s["paused"] is False and s["load_running"] is False
    assert s["draft"] == sse[0][1]["draft"]
    (res,) = s["resolutions"]
    assert res["conflict_id"] == "D01" and res["text"] == text and res["provenance"] == "clinician-provided"
    assert res["chosen_span_id"] == (Q05[0] if how == "pick" else None)
    assert {q["span_id"] for q in res["quotes"]} == QUOTE_SPANS

    carried = [c for c in s["draft"]["claims"] if "D01" in c["clinician_clarification_ids"]]
    assert [c["text"] for c in carried] == [text]
    assert QUOTE_SPANS <= set(carried[0]["evidence_span_ids"]) and carried[0]["support_status"] == "needs_review"
    assert all(c["support_status"] == "unverified" for c in s["draft"]["claims"] if c not in carried)
    assert [(d["discrepancy_id"], set(d["source_span_ids"]), d["status"]) for d in s["draft"]["discrepancies"]] == [
        ("D01", QUOTE_SPANS, "clarified_pending_approval")]

    (prompt,) = [text_of(m) for m in model.kind_calls("summary")]
    assert [(rid, t, set(re.findall(r"note_\d+_p\d+_b\d+", sp))) for rid, t, sp in RESOLVED_LINE.findall(prompt)] == [
        ("D01", text, QUOTE_SPANS)]
    ids = {e["statement"]: e["event_id"] for e in s["events"]}
    assert all(k in prompt for k in ids if k.startswith("KEEP"))
    for statement, eid in ids.items():
        if statement.startswith("DROP"):  # raw conflicting events never reach drafting
            assert statement not in prompt and not re.search(rf"\b{eid}\b", prompt), statement


def test_drafting_failure_after_resume_streams_error_and_clears_flags(client, model):
    sid = paused(client, model)
    model.summary_fail = True
    status, sse = submit(client, sid, [clarify()])
    assert status == 200
    assert sse[-1][0] == "error" and "done" not in [n for n, _ in sse]
    s = state(client, sid)
    assert s["load_running"] is False and s["paused"] is False


def test_export_after_resume_lists_the_resolution(client, model):
    sid = paused(client, model)
    assert submit(client, sid, [pick(Q04[0])])[1][-1][0] == "done"
    assert approve(client, sid).status_code == 200
    md = client.get(f"{PREFIX}/{sid}/export").text
    assert f'- D01: {DESC} — "{DESC}: {Q04[1]}" (clinician-provided; chosen from [N04:B07]) [N04:B07] [N05:B04]' in md
    assert section(md, "Unresolved discrepancies") == ["None flagged."]


# ---------- no conflicts ----------

def test_no_conflicts_streams_straight_to_done(client, model):
    model.conflicts = []
    sid = create(client)
    names = [n for n, _ in load(client, sid)]
    assert "conflicts_found" not in names and names[-3:] == ["extraction_done", "draft", "done"]
    s = state(client, sid)
    assert s["paused"] is False and s["conflicts"] == [] and s["resolutions"] == []


# ---------- 404 / 409 / 422 ----------

def test_resolutions_unknown_session_404(client):
    assert submit(client, "nope", [clarify()])[0] == 404


def test_resolutions_409_when_never_loaded(client):
    assert submit(client, create(client), [clarify()]) == (409, {"detail": "not paused"})


def test_resolutions_409_after_load_without_conflicts(client, model):
    model.conflicts = []
    sid = create(client)
    assert load(client, sid)[-1][0] == "done"
    assert submit(client, sid, [clarify()]) == (409, {"detail": "not paused"})


def test_resolutions_409_on_second_submit(client, model):
    sid = paused(client, model)
    assert submit(client, sid, [clarify()])[1][-1][0] == "done"
    assert submit(client, sid, [clarify()]) == (409, {"detail": "not paused"})


def test_resolutions_409_on_concurrent_submit(client, model):
    sid = paused(client, model)
    drafting, release, first = threading.Event(), threading.Event(), []

    def hold():
        drafting.set()
        release.wait(WAIT)
    model.on_summary = hold
    t = threading.Thread(target=lambda: first.append(submit(TestClient(client.app), sid, [clarify()])))
    t.start()
    try:
        assert drafting.wait(WAIT), "first submit never reached drafting"
        assert submit(client, sid, [clarify()]) == (409, {"detail": "not paused"})
    finally:
        release.set()
        t.join(WAIT)
    assert first[0][0] == 200 and first[0][1][-1][0] == "done"
    assert len(model.kind_calls("summary")) == 1


INVALID = {
    "missing": [],
    "duplicated": [clarify(), clarify()],
    "unknown": [clarify(), clarify(cid="D09")],
    "both": [{"conflict_id": "D01", "chosen_span_id": Q04[0], "clarification": CLARIFICATION}],
    "neither": [{"conflict_id": "D01", "chosen_span_id": None, "clarification": None}],
    "span_not_quoted": [pick(KEEP_SPAN)],
    "blank_clarification": [clarify("   ")],
    "empty_clarification": [clarify("")],
}


@pytest.mark.parametrize("case", INVALID)
def test_invalid_resolutions_422_and_stay_paused(client, model, case):
    sid = paused(client, model)
    assert submit(client, sid, INVALID[case])[0] == 422
    s = state(client, sid)
    assert s["paused"] is True and s["resolutions"] == [] and s["draft"] is None
    assert model.kind_calls("summary") == []
    assert submit(client, sid, [clarify()])[1][-1][0] == "done"  # still resumable


@pytest.mark.parametrize("op", OPERATIONS)
def test_editing_operations_409_while_paused(client, model, asked, op):
    sid = paused(client, model)
    assert call(client, sid, op).status_code == 409
    assert asked == []


def test_new_load_discards_a_pause(client, model):
    sid = paused(client, model)
    first_thread = state(client, sid)["load_thread_id"]
    assert load(client, sid)[-1][0] == "conflicts_found"  # a new load pauses afresh, on a fresh thread
    assert state(client, sid)["load_thread_id"] not in (None, first_thread)

    model.conflicts = []
    assert load(client, sid)[-1][0] == "done"
    s = state(client, sid)
    assert s["paused"] is False and s["conflicts"] == [] and s["resolutions"] == [] and s["load_running"] is False
    assert submit(client, sid, [clarify()]) == (409, {"detail": "not paused"})


# ---------- drafting (core.summarize) ----------

def summary_stub(monkeypatch, *outputs):
    """Each summary call returns the next claims list (the last one repeats); records messages."""
    calls = []

    def parse(schema, messages, timeout):
        assert schema is SummaryResult
        calls.append([dict(m) for m in messages])
        claims = outputs[min(len(calls), len(outputs)) - 1]
        return SummaryResult(claims=[SummaryClaim(claim_id="x", support_status="unverified", **c) for c in claims])
    monkeypatch.setattr(llm, "parse", parse)
    return calls


EVENTS = [ev("Admitted with pneumonia.", (KEEP_SPAN, SPANS[KEEP_SPAN].text)).model_copy(update={"event_id": "E01"})]
ADMITTED = {"section": "reason_for_admission", "text": "Admitted.", "evidence_span_ids": [KEEP_SPAN]}


def test_draft_claim_carrying_a_resolution_gets_all_quote_spans_and_needs_review(monkeypatch):
    calls = summary_stub(monkeypatch, [ADMITTED, {"section": "hospital_course", "text": CLARIFICATION,
                                                  "evidence_span_ids": [Q04[0]], "clinician_clarification_ids": ["D01"]}])
    draft, warnings = generate_draft(EVENTS, SPANS, [resolution()])
    assert len(calls) == 1 and warnings == []
    (prompt,) = [text_of(m) for m in calls]
    assert [(rid, t, set(re.findall(r"note_\d+_p\d+_b\d+", sp))) for rid, t, sp in RESOLVED_LINE.findall(prompt)] == [
        ("D01", CLARIFICATION, QUOTE_SPANS)]
    admitted, resolved = draft.claims
    assert admitted.support_status == "unverified" and admitted.clinician_clarification_ids == []
    assert resolved.clinician_clarification_ids == ["D01"] and resolved.support_status == "needs_review"
    assert set(resolved.evidence_span_ids) == QUOTE_SPANS
    assert draft.discrepancies == []  # the graph sets discrepancies


def test_draft_missing_a_resolution_is_retried_then_appended_with_a_warning(monkeypatch):
    unknown = {"section": "hospital_course", "text": "Course.", "evidence_span_ids": [KEEP_SPAN],
               "clinician_clarification_ids": ["D99"]}
    calls = summary_stub(monkeypatch, [ADMITTED, unknown])  # never carries D01
    draft, warnings = generate_draft(EVENTS, SPANS, [resolution()])

    assert len(calls) == 2  # one validation retry
    first, second = calls
    assert second[:len(first)] == first
    fed_back = text_of([m for m in second[len(first):] if m["role"] != "assistant"])
    assert "D01" in fed_back and "D99" in fed_back

    c1, c2, c3 = draft.claims
    assert (c1.claim_id, c2.claim_id, c3.claim_id) == ("C01", "C02", "C03")
    assert c2.clinician_clarification_ids == [] and c2.support_status == "unverified"  # unknown ID removed
    assert (c3.section, c3.text, c3.clinician_clarification_ids, c3.support_status) == (
        "hospital_course", CLARIFICATION, ["D01"], "needs_review")
    assert set(c3.evidence_span_ids) == QUOTE_SPANS
    assert any("D01" in w for w in warnings)


def test_draft_no_longer_flags_needs_review_events(monkeypatch):
    flagged = EVENTS[0].model_copy(update={"needs_review": True})
    summary_stub(monkeypatch, [ADMITTED])
    draft, _ = generate_draft([flagged], SPANS)
    assert [c.support_status for c in draft.claims] == ["unverified"] and draft.discrepancies == []


# ---------- export (core.export) ----------

def section(md, title):
    lines = md.splitlines()
    i = lines.index(f"## {title}") + 1
    body = []
    for line in lines[i:]:
        if line.startswith("## "):
            break
        if line.strip():
            body.append(line)
    return body


def export(discrepancies, resolutions=None):
    draft = Draft(claims=[SummaryClaim(claim_id="C01", section="reason_for_admission", text="Admitted.",
                                       evidence_span_ids=[KEEP_SPAN], support_status="unverified")],
                  discrepancies=discrepancies)
    if resolutions is None:
        return to_markdown(draft, SPANS, DOCS)
    return to_markdown(draft, SPANS, DOCS, resolutions=resolutions)


D01 = Discrepancy(discrepancy_id="D01", description=DESC, source_span_ids=[Q04[0], Q05[0]],
                  status="clarified_pending_approval")
D02 = Discrepancy(discrepancy_id="D02", description="Oxygen target differs", source_span_ids=[KEEP_SPAN, Q04[0]])


def test_export_lists_picked_resolution_and_only_open_discrepancies():
    md = export([D01, D02], [resolution(f"{DESC}: {Q04[1]}", chosen=Q04[0])])
    assert section(md, "Conflict resolutions") == [
        f'- D01: {DESC} — "{DESC}: {Q04[1]}" (clinician-provided; chosen from [N04:B07]) [N04:B07] [N05:B04]']
    unresolved = section(md, "Unresolved discrepancies")
    assert len(unresolved) == 1 and unresolved[0].startswith("- D02")
    appendix = section(md, "Source appendix")
    assert any(line.startswith("**[N04:B07]**") for line in appendix)
    assert any(line.startswith("**[N05:B04]**") for line in appendix)


def test_export_typed_clarification_and_nothing_open():
    md = export([D01], [resolution()])
    assert section(md, "Conflict resolutions") == [
        f'- D01: {DESC} — "{CLARIFICATION}" (clinician-provided; typed clarification) [N04:B07] [N05:B04]']
    assert section(md, "Unresolved discrepancies") == ["None flagged."]


def test_export_without_resolutions_says_none():
    assert section(export([]), "Conflict resolutions") == ["None."]


# ---------- live ----------

@pytest.mark.live
def test_case_001_pauses_on_medication_a_and_drafts_the_clarification(case_copy):
    name, payload = case_copy.load_sse[-1]
    assert name == "conflicts_found"
    assert [({q["span_id"] for q in c["quotes"]}) for c in payload["conflicts"]] == [QUOTE_SPANS]
    assert "Medication A" in payload["conflicts"][0]["description"]
    carried = [c for c in case_copy.draft.claims if "D01" in c.clinician_clarification_ids]
    assert carried, case_copy.draft.claims
    assert any(QUOTE_SPANS <= set(c.evidence_span_ids) and "5 mg" in c.text and "10 mg" in c.text for c in carried)
