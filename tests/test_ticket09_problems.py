"""Specification tests for ticket 09 (hospital course by problem), see issues/09-contract.md.

Seams: core.load_graph.load_graph.stream (normalization, its warnings, the fallback), the HTTP API through TestClient
(load + resolutions SSE, session state, export) and core.export.to_markdown. The model is stubbed only at
core.llm.parse. Test-imposed interfaces (tests/section_stub.py): the normalization schema is recognized structurally
(a list of {one str name, a raw-label list, a conflict-ID list whose field name contains "conflict"}), and each
hospital_course call names its problem in a "Problem: <name>" line. The 08 rule holds: each section call names
exactly one template section_id.
"""
import threading
import uuid

import pytest

from core import llm
from core.export import to_markdown
from core.extract import ExtractionResult
from core.load_graph import load_graph
from core.models import ClinicalEvent, Draft, SummaryClaim
from tests.section_stub import EVERY_SECTION, IDS, SECTION_EVENTS, dedupe_result, kind, normalization, problem_of, section_of, section_result
from tests.test_api import client, create, state  # noqa: F401  (client is a fixture)
from tests.test_api_ticket04 import approve
from tests.test_ticket06_parallel_load import conflict_result
from tests.test_ticket07_resolve_conflicts import (CLARIFICATION, DESC, DOCS, Q04, Q05, SPANS, clarify, load, plain_span,
                                                  section, submit, text_of)

WAIT = 5
HC = "hospital_course"
OTHER_SECTIONS = [s for s in IDS if s != HC]


def ev(statement, problem, *refs):
    return ClinicalEvent(event_id="x", date_or_hospital_day="Hospital Day 2", category="treatment_documented",
                         statement=statement, problem=problem, evidence=[{"span_id": s, "quote": q} for s, q in refs],
                         sections=EVERY_SECTION)  # ticket 12: routed to every section, as before


def plain(doc):
    s = plain_span(doc)
    return s.span_id, s.text


# Per-note model output. Merged order: note_01..note_06. Raw labels: "CAP" and "community-acquired pneumonia" are one
# problem; "Elevated BP" is left unmapped by the model; note_04's event has no label. DROP events overlap the conflict.
NOTE_EVENTS = {
    "note_01": [ev("EVT_A", "CAP", plain("note_01"))],
    "note_02": [ev("EVT_B", "community-acquired pneumonia", plain("note_02"))],
    "note_03": [ev("EVT_C", "HTN", plain("note_03"))],
    "note_04": [ev("EVT_D", None, (Q04[0], "Intravenous Antibiotic B.")), ev("DROP_1", None, Q04)],
    "note_05": [ev("EVT_E", "Elevated BP", (Q05[0], "First dose of oral Antibiotic B given.")), ev("DROP_2", None, Q05)],
    "note_06": [ev("EVT_F", "CAP", plain("note_06"))],
}
LABELS = {"CAP", "community-acquired pneumonia", "HTN", "Elevated BP"}
KEEP = {"EVT_A": "Pneumonia", "EVT_B": "Pneumonia", "EVT_C": "Hypertension", "EVT_D": "Other", "EVT_E": "Elevated BP",
        "EVT_F": "Pneumonia"}  # statement -> canonical problem under MAPPING
# The model lists problems out of event order, maps HTN and D01 twice (first mapping wins), names labels and conflict
# IDs that do not exist, and leaves "Elevated BP" and (unless added) D01 unmapped.
MAPPING = [("Hypertension", ["HTN"], []), ("Pneumonia", ["community-acquired pneumonia", "CAP", "HTN"], []),
           ("Diabetes", ["DM"], ["D99"])]
ORDER = ["Pneumonia", "Hypertension", "Elevated BP", "Other"]  # first appearance in merged events, Other last
S1, S2, S3 = (plain_span(d).span_id for d in ("note_01", "note_02", "note_03"))


def mapping(d01):
    """MAPPING with D01 mapped to problem d01 (a new first problem if not in MAPPING), and again to the last problem."""
    out = [(p, l, c + ["D01"] * (p == d01)) for p, l, c in MAPPING]
    out = ([] if d01 in {p for p, _, _ in out} else [(d01, [], ["D01"])]) + out
    return out[:-1] + [(out[-1][0], out[-1][1], out[-1][2] + ["D01"])]  # the duplicate mapping is ignored


class Model:
    """Stub for core.llm.parse. outputs: (section_id, problem or None) -> [(documented, [claim dicts]), ...] per attempt
    (last repeats); unlisted calls answer documented=false. calls: (kind, section, problem, messages) per call."""

    def __init__(self):
        self.calls, self.lock = [], threading.Lock()
        self.conflicts = [(DESC, [Q04, Q05])]
        self.problems = MAPPING
        self.normalize_failures = 0                # normalization calls that raise before it answers
        self.outputs = {}
        self.raising = set()                       # (section, problem) keys whose every call raises
        self.on_section = lambda sec, problem: None

    def of(self, k, sec=None, problem=None):
        return [m for kk, s, p, m in self.calls if kk == k and sec in (None, s) and problem in (None, p)]

    def __call__(self, schema, messages, timeout):
        k = kind(schema)
        if k == "extract":
            docs = sorted({SPANS[s].document_id for s in SPANS if s in text_of(messages)})
            return ExtractionResult(events=[e for d in docs for e in NOTE_EVENTS[d]])
        if k == "conflict":
            return conflict_result(schema, self.conflicts)
        if k == "normalize":
            with self.lock:
                self.calls.append((k, None, None, [dict(m) for m in messages]))
                attempt = len(self.of(k))
            if attempt <= self.normalize_failures:
                raise RuntimeError("normalization boom")
            return normalization(schema, self.problems)
        if k == "dedupe":  # ticket 10: nothing to drop
            return dedupe_result(schema)
        sec = section_of(messages)
        problem = problem_of(messages) if sec == HC else None
        with self.lock:
            self.calls.append((k, sec, problem, [dict(m) for m in messages]))
            attempt = len(self.of(k, sec, problem))
        self.on_section(sec, problem)
        if (sec, problem) in self.raising:
            raise RuntimeError(f"{sec}/{problem} boom")
        outs = self.outputs.get((sec, problem), [(False, [])])
        documented, claims = outs[min(attempt, len(outs)) - 1]
        return section_result(schema, documented, [{"section": sec, **c} for c in claims])

    def hc_problems(self):
        return sorted(p for k, s, p, _ in self.calls if s == HC)


@pytest.fixture
def model(monkeypatch):
    m = Model()
    monkeypatch.setattr(llm, "parse", m)
    return m


def claim(text, *spans):
    return {"text": text, "evidence_span_ids": list(spans or [S1])}


def graph_run(thread_id=None):
    return list(load_graph.stream({"documents": DOCS, "spans": SPANS},
                                  {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}, stream_mode="updates"))


def latest(updates, key):
    """The last value any node wrote to state key `key`."""
    found = [v[key] for u in updates for v in u.values() if isinstance(v, dict) and key in v]
    assert found, f"no node wrote {key}"
    return found[-1]


def loaded(client, model):
    """Loads; with conflicts, clarifies D01. Returns (sid, SSE of the drafting stream)."""
    sid = create(client)
    sse = load(client, sid)
    if model.conflicts:
        assert sse[-1][0] == "conflicts_found", sse
        status, sse = submit(client, sid, [clarify()])
        assert status == 200
    assert sse[-1][0] == "done", sse
    return sid, sse


# ---------- normalization ----------

def test_normalization_maps_raw_labels_onto_one_canonical_list_and_code_covers_the_rest(model):
    updates = graph_run()  # pauses on D01: normalization runs before the conflict pause
    assert any("__interrupt__" in u for u in updates)

    (msgs,) = model.of("normalize")  # one call, after merge
    prompt = text_of(msgs)
    assert all(label in prompt for label in LABELS)
    assert f"D01 | {DESC} |" in prompt  # one line per conflict: D01 | description | quotes
    assert not model.of("summary")

    events = {e.statement: e.problem for e in latest(updates, "events")}
    assert {s: events[s] for s in KEEP} == KEEP  # synonyms merged; unmapped label is its own problem; null -> Other
    assert events["DROP_1"] == events["DROP_2"] == "Other"
    assert all(events.values())  # every event has exactly one canonical problem

    warnings = " ".join(latest(updates, "extract_warnings"))
    for fixed in ("Elevated BP", "HTN", "D01"):  # unmapped label, label mapped twice, unmapped conflict
        assert fixed in warnings, (fixed, warnings)


@pytest.mark.parametrize("failures", [1, 2])
def test_normalization_retries_once_then_falls_back_to_raw_labels_and_the_load_completes(model, failures):
    model.conflicts = []
    model.normalize_failures = failures
    updates = graph_run()
    assert latest(updates, "draft") is not None  # normalization never fails the load
    assert len(model.of("normalize")) == 2

    events = {e.statement: e.problem for e in latest(updates, "events")}
    if failures == 1:  # the retry answered
        assert {s: events[s] for s in KEEP} == KEEP
        assert model.hc_problems() == sorted(ORDER)
    else:  # fallback: each distinct raw label is its own problem, null labels go to Other, and a warning says so
        assert {s: events[s] for s in KEEP} == {"EVT_A": "CAP", "EVT_B": "community-acquired pneumonia", "EVT_C": "HTN",
                                                 "EVT_D": "Other", "EVT_E": "Elevated BP", "EVT_F": "CAP"}
        assert model.hc_problems() == sorted(LABELS | {"Other"})
        assert len(latest(updates, "extract_warnings")) > 0


# ---------- per-problem hospital course calls ----------

def test_one_hospital_course_call_per_problem_concurrently_with_only_its_events_and_resolutions(client, model):
    model.problems = mapping(d01="Medication A dosing")  # a problem that has a resolution but no events
    cv, live = threading.Condition(), {"now": 0, "max": 0, "started": 0}
    expected = sorted(ORDER + ["Medication A dosing"])  # Diabetes has neither events nor resolutions: no call

    def hold(sec, problem):  # hospital_course calls stay in flight until all have started (or 1 s passes)
        if sec != HC:
            return
        with cv:
            live["now"] += 1
            live["started"] += 1
            live["max"] = max(live["max"], live["now"])
            cv.notify_all()
            cv.wait_for(lambda: live["started"] == len(expected), timeout=1)
            live["now"] -= 1
    model.on_section = hold
    loaded(client, model)

    assert model.hc_problems() == expected
    assert live["max"] >= 2, live
    for problem in expected:
        (msgs,) = model.of("summary", HC, problem)
        prompt = text_of(msgs)
        assert {s for s in KEEP if s in prompt} == {s for s, p in KEEP.items() if p == problem}, problem
        assert (CLARIFICATION in prompt) == (problem == "Medication A dosing"), problem
        assert "DROP_" not in prompt
    for sec in OTHER_SECTIONS:  # unchanged from 08: all non-conflicting events and all resolutions, one call each
        (msgs,) = model.of("summary", sec)
        prompt = text_of(msgs)
        assert all(s in prompt for s in KEEP) and CLARIFICATION in prompt and "DROP_" not in prompt


# ---------- claims, numbering, fallback ----------

def test_claims_carry_problem_numbered_in_template_then_problem_order_whatever_the_completion_order(client, model):
    model.problems = mapping(d01="Hypertension")  # D01 maps to Hypertension (its later Diabetes mapping is ignored)
    model.outputs = {  # no claim carries D01: code appends it last in the Hypertension group
        ("reason_for_admission", None): [(True, [claim("Admitted.", S1)])],
        (HC, "Other"): [(True, [claim("Other course.", S1)])],
        (HC, "Elevated BP"): [(True, [claim("BP course.", S2)])],
        (HC, "Hypertension"): [(True, [claim("HTN course.", S3)])],
        (HC, "Pneumonia"): [(True, [claim("Zeta pneumonia.", S1), claim("Alpha pneumonia.", S2)])],
        ("follow_up", None): [(True, [claim("Follow up.", S3)])],
    }
    expected = [("C01", "reason_for_admission", None, "Admitted."),
                ("C02", HC, "Pneumonia", "Zeta pneumonia."), ("C03", HC, "Pneumonia", "Alpha pneumonia."),
                ("C04", HC, "Hypertension", "HTN course."), ("C05", HC, "Hypertension", CLARIFICATION),
                ("C06", HC, "Elevated BP", "BP course."), ("C07", HC, "Other", "Other course."),
                ("C08", "follow_up", None, "Follow up.")]
    runs = []
    for gated in (False, True):
        other_done, late = threading.Event(), []

        def gate(sec, problem, gated=gated, other_done=other_done, late=late):
            if (sec, problem) == (HC, "Other"):
                other_done.set()
            elif gated and (sec, problem) == (HC, "Pneumonia") and not other_done.wait(WAIT):
                late.append(problem)  # Pneumonia finishes only after Other
        model.on_section = gate
        model.calls.clear()
        sid, sse = loaded(client, model)
        assert not late, "completion order could not be forced"
        assert model.hc_problems() == sorted(ORDER)  # the fallback claim costs no extra model call
        draft = state(client, sid)["draft"]
        assert draft == dict(sse)["draft"]["draft"]  # the final snapshot carries problem too
        runs.append([(c["claim_id"], c["section"], c["problem"], c["text"]) for c in draft["claims"]])
        fallback = draft["claims"][4]
        assert fallback["clinician_clarification_ids"] == ["D01"] and fallback["support_status"] == "needs_review"
    assert runs[0] == expected and runs[1] == expected


# ---------- SSE and export ----------

def test_section_drafted_per_problem_carries_problem_and_undocumented_groups_are_not_shown(client, model):
    model.conflicts = []
    model.outputs = {
        ("reason_for_admission", None): [(True, [claim("Admitted.", S1)])],
        (HC, "Pneumonia"): [(True, [claim("Pneumonia course.", S1)])],
        (HC, "Hypertension"): [(True, [claim("HTN course.", S3)])],
        (HC, "Other"): [(True, [claim("Other course.", S2)])],
        # (HC, "Elevated BP"): documented=false
        ("follow_up", None): [(True, [claim("Follow up.", S3)])],
    }
    sid, sse = loaded(client, model)
    names = [n for n, _ in sse]
    i = names.index("extraction_done") + 1
    n_events = len(OTHER_SECTIONS) + len(ORDER)
    assert set(names[i:i + n_events]) <= set(SECTION_EVENTS) and names[i + n_events:] == ["dedupe_applied", "draft", "done"]

    hc = [d for n, d in sse if n == "section_drafted" and d["section_id"] == HC]
    assert sorted(d["problem"] for d in hc) == sorted(ORDER)  # one per problem call, none omitted
    assert next(d for d in hc if d["problem"] == "Elevated BP")["claims"] == []
    assert not [d for n, d in sse if n == "section_omitted" and d["section_id"] == HC]
    assert all(d["problem"] is None for n, d in sse if n == "section_drafted" and d["section_id"] != HC)
    assert [c["text"] for d in hc if d["problem"] == "Pneumonia" for c in d["claims"]] == ["Pneumonia course."]

    claims = state(client, sid)["draft"]["claims"]
    assert [c["problem"] for c in claims if c["section"] == HC] == ["Pneumonia", "Hypertension", "Other"]
    assert approve(client, sid).status_code == 200
    md = client.get(f"/api/sessions/{sid}/export").text
    body = section(md, "Hospital course")
    assert [line for line in body if line.startswith("### ")] == ["### Pneumonia", "### Hypertension", "### Other"]
    assert body[body.index("### Pneumonia") + 1].startswith("- Pneumonia course.")


def test_problem_call_failing_after_its_retry_fails_the_load(client, model):
    model.conflicts = []
    model.raising = {(HC, "Hypertension")}
    sid = create(client)
    sse = load(client, sid)
    names = [n for n, _ in sse]
    assert names[-1] == "error" and "draft" not in names and "done" not in names
    assert len(model.of("summary", HC, "Hypertension")) == 2
    s = state(client, sid)
    assert s["load_running"] is False and s["draft"] is None


def test_export_groups_hospital_course_under_problem_subheadings():
    def c(cid, section, text, problem=None):
        return SummaryClaim(claim_id=cid, section=section, text=text, evidence_span_ids=[S1], support_status="unverified",
                            problem=problem)
    draft = Draft(claims=[c("C01", "reason_for_admission", "Admitted."),
                          c("C02", HC, "Pneumonia one.", "Pneumonia"), c("C03", HC, "Pneumonia two.", "Pneumonia"),
                          c("C04", HC, "HTN one.", "Hypertension"),
                          c("C05", HC, "Correction without problem."),
                          c("C06", "follow_up", "Follow up.")])
    md = to_markdown(draft, SPANS, DOCS)
    lines = section(md, "Hospital course")
    assert [ln if ln.startswith("### ") else ln.split(" [N")[0] for ln in lines] == [
        "- Correction without problem.",  # no problem: no subheading, at the top
        "### Pneumonia", "- Pneumonia one.", "- Pneumonia two.",
        "### Hypertension", "- HTN one."]
    assert not [ln for ln in section(md, "Reason for admission") + section(md, "Follow-up") if ln.startswith("#")]


# ---------- live ----------

@pytest.mark.live
def test_case_001_hospital_course_has_pneumonia_and_hypertension_groups(case_copy):
    problems = {c.problem.lower() for c in case_copy.draft.claims if c.section == HC and c.problem}
    assert any("pneumonia" in p for p in problems), problems
    assert any("hypertension" in p for p in problems), problems
