"""Specification tests for ticket 12 (route events to sections), see issues/12-contract.md.

Seams: ClinicalEvent / ExtractionResult schema validation, core.extract.extract_events, and the HTTP API through
TestClient (load + resolutions SSE, session state), which drives core.load_graph.load_graph. The model is stubbed only at
core.llm.parse with the ticket 11 stub (tests/test_ticket11_note_retry.py): it records every section call's messages, so
a test reads which event statements and which resolution text reached which (section, problem) call.

Test-imposed interfaces: none beyond the contract's `ClinicalEvent.sections` field and the earlier stub seams.
"""
import re

import pytest
from pydantic import ValidationError

from core import extract, llm
from core.extract import ExtractionResult
from core.models import TEMPLATE, ClinicalEvent
from tests.section_stub import IDS, SECTION_EVENTS
from tests.test_api import client, create, state  # noqa: F401  (client is a fixture)
from tests.test_ticket07_resolve_conflicts import CLARIFICATION, DESC, DOCS, Q04, Q05, SPANS, plain_span, text_of
from tests.test_ticket11_note_retry import after_first_draft, drafts, model, run, settled  # noqa: F401  (model is a fixture)

HC = "hospital_course"
NON_HC = [s for s in IDS if s != HC]
OPTIONAL = {s["section_id"] for s in TEMPLATE if s["optional"]}
MAPPING = [("Pneumonia", ["CAP"], ["D01"]), ("Hypertension", ["HTN"], [])]


def ev(statement, label, sections, ref=None, doc=None):
    s = plain_span(doc) if doc else None
    span, quote = ref or (s.span_id, s.text)
    return ClinicalEvent(event_id="x", date_or_hospital_day="Hospital Day 2", category="other", statement=statement,
                         problem=label, sections=sections, evidence=[{"span_id": span, "quote": quote}])


def scenario(condition_tagged=True):
    """Per-note extraction output, with D01 (Q04 / Q05). Every required section other than hospital_course has a
    routed event unless condition_tagged is False (then condition_at_discharge has none). dose_04 / dose_05 overlap the
    D01 quotes; key_fact shares Q04's passage without overlapping it."""
    other_05 = plain_span("note_05", exclude={Q05[0]})
    return {
        "note_01": [ev("rfa_fact", "CAP", ["reason_for_admission", "discharge_diagnoses"], doc="note_01")],
        "note_02": [ev("med_fact", "HTN", ["discharge_medications"], doc="note_02")],
        "note_03": [ev("untagged_fact", "CAP", [], doc="note_03")],
        "note_04": [ev("key_fact", "CAP", ["key_events"], (Q04[0], "Intravenous Antibiotic B.")),
                    ev("dose_04", None, ["discharge_medications"], Q04)],
        "note_05": [ev("dose_05", None, ["pending_items"], Q05),
                    ev("followup_fact", "HTN", ["follow_up", "key_events"] + ["condition_at_discharge"] * condition_tagged,
                       (other_05.span_id, other_05.text))],
        "note_06": [ev("other_fact", None, [], doc="note_06")],
    }


NON_CONFLICTING = ["rfa_fact", "med_fact", "untagged_fact", "key_fact", "followup_fact", "other_fact"]
STATEMENTS = NON_CONFLICTING + ["dose_04", "dose_05"]


def seen(messages):
    return {s for s in STATEMENTS if re.search(rf"\b{s}\b", text_of(messages))}


def calls(model):
    """(section, problem) -> list of message lists, one per call."""
    out = {}
    for sec, problem, m in model.summary:
        out.setdefault((sec, problem), []).append(m)
    return out


@pytest.fixture
def routed(client, model):
    """Loads the scenario and clarifies D01. Returns (sid, resume SSE)."""
    model.events = scenario()
    model.conflicts = [(DESC, [Q04, Q05])]
    model.normalize = [MAPPING]
    sid, _, resumed = run(client, model)
    assert resumed[-1][0] == "done", resumed
    return sid, resumed


# ---------- schema ----------

def test_sections_tag_accepts_only_template_sections_other_than_hospital_course():
    base = dict(event_id="E01", date_or_hospital_day=None, category="other", statement="s",
                evidence=[{"span_id": "note_01_p01_b01", "quote": "q"}])
    assert ClinicalEvent.model_validate(base).sections == []  # default: hospital course only
    assert ClinicalEvent.model_validate({**base, "sections": NON_HC}).sections == NON_HC
    for bad in (HC, "not_a_section"):
        with pytest.raises(ValidationError):
            ClinicalEvent.model_validate({**base, "sections": ["follow_up", bad]})


def test_extraction_schema_sent_to_the_model_enumerates_exactly_the_routable_sections():
    js = ExtractionResult.model_json_schema()
    event = js["$defs"]["ClinicalEvent"]
    items = event["properties"]["sections"]["items"]
    if "$ref" in items:
        items = js["$defs"][items["$ref"].split("/")[-1]]
    assert sorted(items["enum"]) == sorted(NON_HC)


def test_extraction_keeps_each_events_section_tags(monkeypatch):
    tagged = [ev("a", None, ["key_events", "follow_up"], doc="note_01"), ev("b", None, [], doc="note_01")]
    monkeypatch.setattr(llm, "parse", lambda schema, messages, timeout: ExtractionResult(events=tagged))
    doc = next(d for d in DOCS if d.document_id == "note_01")
    events, errors = extract.extract_events([doc], {k: v for k, v in SPANS.items() if v.document_id == "note_01"})
    assert errors == []
    assert [(e.statement, e.sections) for e in events] == [("a", ["key_events", "follow_up"]), ("b", [])]


def test_session_events_keep_their_section_tags(client, routed):
    sid, _ = routed
    tags = {e["statement"]: e["sections"] for e in state(client, sid)["events"]}
    assert tags["rfa_fact"] == ["reason_for_admission", "discharge_diagnoses"]
    assert tags["untagged_fact"] == [] and tags["dose_05"] == ["pending_items"]


# ---------- events ----------

def test_each_section_other_than_hospital_course_receives_exactly_its_routed_non_conflicting_events(model, routed):
    by = calls(model)
    expected = {"reason_for_admission": {"rfa_fact"}, "discharge_diagnoses": {"rfa_fact"},
                "key_events": {"key_fact", "followup_fact"}, "condition_at_discharge": {"followup_fact"},
                "discharge_medications": {"med_fact"}, "follow_up": {"followup_fact"}, "pending_items": set()}
    for sec, statements in expected.items():
        assert len(by[(sec, None)]) == 1, sec
        assert seen(by[(sec, None)][0]) == statements, sec


def test_an_untagged_event_reaches_only_the_hospital_course_call_for_its_problem(model, routed):
    reached = sorted((sec, p) for (sec, p), ms in calls(model).items() for m in ms if "untagged_fact" in seen(m))
    assert reached == [(HC, "Pneumonia")]
    assert seen(calls(model)[(HC, "Pneumonia")][0]) == {"rfa_fact", "untagged_fact", "key_fact"}
    assert seen(calls(model)[(HC, "Hypertension")][0]) == {"med_fact", "followup_fact"}
    assert seen(calls(model)[(HC, "Other")][0]) == {"other_fact"}  # untagged, no problem: Other, as in 09


def test_raw_conflicting_events_never_reach_drafting(model, routed):
    assert not any({"dose_04", "dose_05"} & seen(m) for _, _, m in model.summary)


def test_required_section_with_nothing_routed_gets_every_non_conflicting_event(client, model):
    model.events = scenario(condition_tagged=False)
    model.conflicts = [(DESC, [Q04, Q05])]
    model.normalize = [MAPPING]
    _, _, resumed = run(client, model)
    assert resumed[-1][0] == "done", resumed

    by = calls(model)
    assert len(by[("condition_at_discharge", None)]) == 1
    assert seen(by[("condition_at_discharge", None)][0]) == set(NON_CONFLICTING)
    assert seen(by[("reason_for_admission", None)][0]) == {"rfa_fact"}  # routed required sections keep their routing
    assert ("procedures", None) not in by and ("patient_instructions", None) not in by  # never for optional sections


def test_optional_section_with_nothing_routed_makes_no_call_and_streams_section_omitted(client, model, routed):
    sid, sse = routed
    by = calls(model)
    nothing = {"procedures", "patient_instructions"}  # no routed events, no routed resolution
    assert not nothing & {sec for sec, _ in by}
    assert ("pending_items", None) in by  # a routed resolution alone is enough for a call
    omitted = [d for n, d in sse if n == "section_omitted"]
    assert nothing <= {d["section_id"] for d in omitted}
    ids = [d["section_id"] for n, d in sse if n in SECTION_EVENTS]  # still one section event per section
    assert sorted(i for i in ids if i != HC) == sorted(NON_HC)
    assert not nothing & {c["section"] for c in state(client, sid)["draft"]["claims"]}


# ---------- resolutions ----------

def test_resolution_reaches_a_section_only_through_its_tagged_raw_conflicting_events_and_always_its_problem(model, routed):
    by = calls(model)
    carried = {k for k, ms in by.items() if any(CLARIFICATION in text_of(m) for m in ms)}
    # dose_04 is tagged discharge_medications, dose_05 pending_items; key_fact shares Q04's passage without overlapping
    assert carried == {("discharge_medications", None), ("pending_items", None), (HC, "Pneumonia")}


# ---------- ticket 11 redraft ----------

def test_recovered_note_redrafts_only_sections_whose_routed_input_changed(client, model):
    """note_02 recovers on retry with one event tagged key_events, problem HTN (Hypertension). condition_at_discharge
    has nothing routed, so it is on the fallback (every event) and its input changes. Routed events of the other sections
    are unchanged in content, though their event IDs shift."""
    model.events = {
        "note_01": [ev("rfa_fact", "CAP", ["reason_for_admission", "key_events"], doc="note_01")],
        "note_02": [ev("recovered_fact", "HTN", ["key_events"], doc="note_02")],
        "note_03": [ev("followup_fact", "HTN", ["follow_up"], doc="note_03")],
        "note_04": [ev("dx_fact", "CAP", ["discharge_diagnoses"], doc="note_04")],
        "note_05": [ev("med_fact", "HTN", ["discharge_medications"], doc="note_05")],
        "note_06": [ev("other_fact", None, [], doc="note_06")],
    }
    model.normalize = [MAPPING]
    model.fails = {"note_02": 2}
    sid, sse, _ = run(client, model)
    assert sse[-1][0] == "done", sse

    first = {("reason_for_admission", None), ("key_events", None), ("follow_up", None), ("discharge_diagnoses", None),
             ("discharge_medications", None), ("condition_at_discharge", None),
             (HC, "Pneumonia"), (HC, "Hypertension"), (HC, "Other")}
    redrafted = {("key_events", None), ("condition_at_discharge", None), (HC, "Hypertension")}
    assert dict(model.section_counts()) == {k: 1 + (k in redrafted) for k in first}

    retrying, settles, rest = settled(sse)
    assert retrying == ["note_02"] and settles["note_02"][0] == "note_extracted"
    assert rest[-3:] == ["dedupe_applied", "draft", "done"]
    tail = [(d["section_id"], d["problem"]) for n, d in after_first_draft(sse) if n in SECTION_EVENTS]
    assert sorted(tail, key=str) == sorted(redrafted, key=str)
    for k in redrafted:  # the redraft carries the recovered event
        assert "recovered_fact" in text_of(calls(model)[k][-1]), k
    assert "recovered_fact" in [c["text"] for c in drafts(sse)[-1]["draft"]["claims"]]


# ---------- live ----------

@pytest.mark.live
def test_case_001_routed_load_records_counts_and_times_and_keeps_the_required_content(case_copy):
    final = len(case_copy.draft.claims)
    removed = dict(case_copy.sse)["dedupe_applied"]["count"]
    print(f"\ncase_001 claims before dedupe: {final + removed} (removed {removed}, final {final}); "
          f"resume to done: {case_copy.resume_seconds:.1f} s; dedupe call: "
          + ", ".join(f"{t:.1f} s" for t in case_copy.dedupe_seconds))
    claims = case_copy.draft.claims
    assert {"discharge_diagnoses", "follow_up"} <= {c.section for c in claims}
    problems = {c.problem.lower() for c in claims if c.section == HC and c.problem}
    assert any("pneumonia" in p for p in problems), problems
    assert any("hypertension" in p for p in problems), problems
    d01 = next(c for c in case_copy.conflicts if c["conflict_id"] == "D01")
    quotes = {q["span_id"] for q in d01["quotes"]}
    assert any("D01" in c.clinician_clarification_ids and quotes <= set(c.evidence_span_ids) for c in claims)
    assert all(c.evidence_span_ids and all(s in case_copy.spans for s in c.evidence_span_ids) for c in claims)
