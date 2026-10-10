"""Specification tests for ticket 08 (section-by-section drafting), see issues/08-contract.md.

Seams: the HTTP API (load + resolutions SSE, session state, export) through TestClient; the model is stubbed only at
core.llm.parse. Section calls are recognized as in tests/section_stub.py (test-imposed: the schema has a `documented`
field; the call's messages before any retry name exactly one template section_id).
"""
import threading
from collections import Counter

import pytest

from core import llm
from core.export import NOT_DOCUMENTED
from core.extract import ExtractionResult
from tests.section_stub import IDS, OPTIONAL, SECTION_EVENTS, dedupe_result, kind, normalization, section_of, section_result
from tests.test_api import client, create, state  # noqa: F401  (client is a fixture)
from tests.test_api_ticket04 import approve
from tests.test_ticket06_parallel_load import conflict_result
from tests.test_ticket07_resolve_conflicts import (DESC, Q04, Q05, SPANS, clarify, events_for, load, plain_span, section,
                                                  submit, text_of)

WAIT = 5
BAD_SPAN = "note_99_p01_b01"
S1, S2, S3 = (plain_span(d).span_id for d in ("note_01", "note_02", "note_03"))


class Model:
    """Stub for core.llm.parse. outputs: section_id -> [(documented, [claim dicts]), ...] per attempt (last repeats);
    sections not listed answer documented=false. calls: (section_id, messages) per drafting call."""

    def __init__(self):
        self.calls, self.lock = [], threading.Lock()
        self.conflicts = []
        self.outputs = {}
        self.raising = set()                       # sections whose every call raises
        self.on_section = lambda sec: None         # runs inside each section call, before it returns

    def sections(self, sec=None):
        return [m for s, m in self.calls if sec in (None, s)]

    def __call__(self, schema, messages, timeout):
        k = kind(schema)
        if k == "extract":
            docs = sorted({SPANS[s].document_id for s in SPANS if s in text_of(messages)})
            return ExtractionResult(events=[e for d in docs for e in events_for(d)])
        if k == "conflict":
            return conflict_result(schema, self.conflicts)
        if k == "normalize":  # ticket 09: maps nothing; code puts unlabeled events and conflicts under one problem
            return normalization(schema)
        if k == "dedupe":  # ticket 10: nothing to drop
            return dedupe_result(schema)
        sec = section_of(messages)
        with self.lock:
            self.calls.append((sec, [dict(m) for m in messages]))
            attempt = len(self.sections(sec))
        self.on_section(sec)
        if sec in self.raising:
            raise RuntimeError(f"{sec} boom")
        outs = self.outputs.get(sec, [(False, [])])
        documented, claims = outs[min(attempt, len(outs)) - 1]
        return section_result(schema, documented, [{"section": sec, **c} for c in claims])


@pytest.fixture
def model(monkeypatch):
    m = Model()
    monkeypatch.setattr(llm, "parse", m)
    return m


def claim(text, *spans, **kw):
    return {"text": text, "evidence_span_ids": list(spans or [S1]), **kw}


def section_events(sse):
    return [(n, d) for n, d in sse if n in SECTION_EVENTS]


def loaded(client):
    sid = create(client)
    sse = load(client, sid)
    assert sse[-1][0] == "done", sse
    return sid, sse


# ---------- one call per section, concurrent, after resolution ----------

def test_one_draft_call_per_section_concurrently_and_only_after_resolution(client, model):
    model.conflicts = [(DESC, [Q04, Q05])]
    sid = create(client)
    assert load(client, sid)[-1][0] == "conflicts_found"
    assert model.calls == []  # nothing drafted before resolution

    cv, live = threading.Condition(), {"now": 0, "max": 0, "started": 0}

    def hold(sec):  # each call stays in flight until all have started (or 1 s passes, as it must under a cap)
        with cv:
            live["now"] += 1
            live["started"] += 1
            live["max"] = max(live["max"], live["now"])
            cv.notify_all()
            cv.wait_for(lambda: live["started"] == len(IDS), timeout=1)
            live["now"] -= 1
    model.on_section = hold
    status, sse = submit(client, sid, [clarify()])
    assert status == 200 and sse[-1][0] == "done", sse
    assert sorted(s for s, _ in model.calls) == sorted(IDS)  # exactly one call per template section
    assert 2 <= live["max"] <= 6, live


# ---------- documented decisions ----------

def test_documented_false_and_empty_sections(client, model):
    model.outputs = {
        "reason_for_admission": [(True, [claim("Admitted with pneumonia.", S1)])],
        "hospital_course": [(True, [claim("Treated with antibiotics.", S2)])],
        "follow_up": [(True, [claim("Follow up in one week.", S3)])],
        "discharge_medications": [(True, [])],  # optional, documented but empty -> warning
        # condition_at_discharge (required) and every other optional section: documented=false
    }
    sid, sse = loaded(client)
    events = section_events(sse)
    assert sorted(d["section_id"] for _, d in events) == sorted(IDS)  # one event per section
    omitted = {d["section_id"] for n, d in events if n == "section_omitted"}
    assert omitted == OPTIONAL - {"discharge_medications"}  # optional + documented=false only
    assert all(d == {"section_id": d["section_id"]} for n, d in events if n == "section_omitted")
    drafted = {d["section_id"]: d for n, d in events if n == "section_drafted"}
    assert [{k: c[k] for k in ("section", "text", "evidence_span_ids")} for c in drafted["reason_for_admission"]["claims"]] == [
        {"section": "reason_for_admission", "text": "Admitted with pneumonia.", "evidence_span_ids": [S1]}]
    assert drafted["condition_at_discharge"]["claims"] == []  # required + documented=false: no claims
    assert drafted["discharge_medications"]["claims"] == []

    draft = state(client, sid)["draft"]
    assert {c["section"] for c in draft["claims"]} == {"reason_for_admission", "hospital_course", "follow_up"}
    assert any("discharge_medications" in w for w in dict(sse)["draft"]["warnings"])

    assert approve(client, sid).status_code == 200
    md = client.get(f"/api/sessions/{sid}/export").text
    assert section(md, "Condition at discharge") == [NOT_DOCUMENTED]
    assert "## Discharge diagnoses" not in md and "## Procedures" not in md and "## Discharge medications" not in md
    assert section(md, "Follow-up")[0].startswith("- Follow up in one week.")


# ---------- numbering ----------

def test_numbering_follows_template_and_model_order_whatever_the_completion_order(client, model):
    model.outputs = {  # model order within a section is not alphabetical, to catch sorting by text
        "reason_for_admission": [(True, [claim("Zeta admitted.", S1), claim("Alpha admitted.", S2)])],
        "hospital_course": [(True, [claim("Course.", S2)])],
        "follow_up": [(True, [claim("Yankee follow-up.", S3), claim("Bravo follow-up.", S1)])],
    }
    expected = [("C01", "reason_for_admission", "Zeta admitted."), ("C02", "reason_for_admission", "Alpha admitted."),
                ("C03", "hospital_course", "Course."), ("C04", "follow_up", "Yankee follow-up."),
                ("C05", "follow_up", "Bravo follow-up.")]
    runs = []
    for gated in (False, True):
        follow_up_done, late = threading.Event(), []

        def gate(sec, gated=gated, follow_up_done=follow_up_done, late=late):
            if sec == "follow_up":
                follow_up_done.set()
            elif gated and sec == "reason_for_admission" and not follow_up_done.wait(WAIT):
                late.append(sec)  # reason_for_admission finishes only after follow_up
        model.on_section = gate
        sid, _ = loaded(client)
        assert not late, "completion order could not be forced"
        runs.append([(c["claim_id"], c["section"], c["text"]) for c in state(client, sid)["draft"]["claims"]])
    assert runs[0] == expected and runs[1] == expected


# ---------- per-section validation retry ----------

@pytest.mark.parametrize("error, bad, mention", [
    ("unknown_span", claim("Follow up in one week.", BAD_SPAN), BAD_SPAN),
    ("wrong_section", claim("Bronchoscopy performed.", S2, section="procedures"), "procedures"),
])
def test_validation_error_retries_only_that_section(client, model, error, bad, mention):
    good = claim("Follow up in one week.", S3)
    model.outputs = {"reason_for_admission": [(True, [claim("Admitted.", S1)])],
                     "follow_up": [(True, [bad]), (True, [good])]}
    sid, _ = loaded(client)

    first, second = model.sections("follow_up")  # one retry, with the error fed back
    assert second[:len(first)] == first and len(second) > len(first)
    assert mention in text_of([m for m in second[len(first):] if m["role"] != "assistant"])
    assert Counter(s for s, _ in model.calls) == Counter(IDS + ["follow_up"])  # no other section re-called

    claims = state(client, sid)["draft"]["claims"]
    assert [(c["section"], c["text"], c["evidence_span_ids"]) for c in claims if c["section"] == "follow_up"] == [
        ("follow_up", "Follow up in one week.", [S3])]
    assert not [c for c in claims if c["section"] == "procedures"]


# ---------- section failure ----------

@pytest.mark.parametrize("how", ["exception", "no_valid_claims"])
def test_section_failing_after_its_retry_fails_the_load_and_retry_reruns_it(client, model, how):
    model.outputs = {"reason_for_admission": [(True, [claim("Admitted.", S1)])]}
    if how == "exception":
        model.raising = {"follow_up"}
    else:
        model.outputs["follow_up"] = [(True, [claim("Follow up.", BAD_SPAN)])]  # invalid on both attempts
    sid = create(client)
    sse = load(client, sid)
    names = [n for n, _ in sse]
    assert names[-1] == "error" and sse[-1][1]["detail"] and "draft" not in names and "done" not in names
    assert len(model.sections("follow_up")) == 2
    s = state(client, sid)
    assert s["load_running"] is False and s["paused"] is False and s["draft"] is None

    model.raising, model.outputs["follow_up"] = set(), [(True, [claim("Follow up.", S3)])]
    assert load(client, sid)[-1][0] == "done"  # Retry reruns the load
    assert state(client, sid)["draft"]["claims"]


# ---------- SSE order ----------

def test_section_events_stream_before_draft_then_done_on_load_and_resume(client, model):
    model.outputs = {"reason_for_admission": [(True, [claim("Admitted.", S1)])]}
    _, sse = loaded(client)
    names = [n for n, _ in sse]
    i = names.index("extraction_done") + 1
    assert set(names[i:i + len(IDS)]) <= set(SECTION_EVENTS) and names[i + len(IDS):] == ["dedupe_applied", "draft", "done"]

    model.conflicts = [(DESC, [Q04, Q05])]
    sid = create(client)
    assert load(client, sid)[-1][0] == "conflicts_found"
    status, sse = submit(client, sid, [clarify()])
    names = [n for n, _ in sse]
    assert status == 200 and set(names[:len(IDS)]) <= set(SECTION_EVENTS) and names[len(IDS):] == ["dedupe_applied", "draft", "done"]
    assert state(client, sid)["draft"] == dict(sse)["draft"]["draft"]


# ---------- live ----------

@pytest.mark.live
def test_case_001_draft_has_diagnoses_follow_up_citations_and_the_resolution(case_copy):
    claims = case_copy.draft.claims
    sections = {c.section for c in claims}
    assert {"discharge_diagnoses", "follow_up"} <= sections, sections
    assert all(c.evidence_span_ids and all(s in case_copy.spans for s in c.evidence_span_ids) for c in claims)
    quotes = {Q04[0], Q05[0]}
    assert any("D01" in c.clinician_clarification_ids and quotes <= set(c.evidence_span_ids) for c in claims)
    names = [n for n, _ in case_copy.sse]
    # ticket 09: hospital_course streams one section event per problem; every other section exactly once
    ids = [d["section_id"] for n, d in case_copy.sse if n in SECTION_EVENTS]
    assert sorted(i for i in ids if i != "hospital_course") == sorted(i for i in IDS if i != "hospital_course")
    assert "hospital_course" in ids
