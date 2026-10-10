"""Specification tests for ticket 10 (dedupe), see issues/10-contract.md.

Seams: the HTTP API through TestClient (load + resolutions SSE, session state). The model is stubbed only at
core.llm.parse; the dedupe call is recognized by a schema with a `drop_claim_ids` field (tests/section_stub.py), and its
stubbed answer is built with model_construct, so out-of-set IDs reach the code. Section/problem drafting reuses the
ticket 09 stub (no conflicts: problems Pneumonia, Hypertension, Elevated BP, Other).
Test-imposed: a refused drop's warning (in the `draft` event's warnings) contains the claim's pre-dedupe ID or its text,
and the reason ("resolution"/the D ID for the resolution guard).
"""
import pytest
from pydantic import ValidationError

from tests.section_stub import IDS, SECTION_EVENTS, dedupe_result, kind
from tests.test_api import client, create, load, state  # noqa: F401  (client is a fixture)
from tests.test_ticket07_resolve_conflicts import DESC, Q04, Q05, clarify, submit
from tests.test_ticket09_problems import HC, ORDER, S1, S2, S3
from tests.test_ticket09_problems import Model as SectionModel

# The joined draft, in template order then problem order: (claim ID, section, problem, text, span).
BASE = [
    ("C01", "reason_for_admission", None, "Admitted with pneumonia.", S1),
    ("C02", "discharge_diagnoses", None, "Community-acquired pneumonia.", S1),
    ("C03", HC, "Pneumonia", "Started IV antibiotics.", S1),
    ("C04", HC, "Pneumonia", "Chest X-ray showed right lower lobe consolidation.", S2),
    ("C05", HC, "Hypertension", "Amlodipine continued.", S3),
    ("C06", "key_events", None, "Chest X-ray showed right lower lobe consolidation.", S2),
    ("C07", "key_events", None, "Blood cultures negative.", S1),
    ("C08", "discharge_medications", None, "Amlodipine 5 mg daily.", S3),
    ("C09", "discharge_medications", None, "Oral Antibiotic B.", S1),
    ("C10", "follow_up", None, "Follow up with PCP in 1 week.", S3),
]
TEXT = {cid: text for cid, _, _, text, _ in BASE}
N_SECTION_EVENTS = len(IDS) - 1 + len(ORDER)
CONFLICT = (DESC, [Q04, Q05])  # D01, as in tickets 07/09


class Model(SectionModel):
    """Adds the dedupe call: drops (answer, per attempt), dedupe_failures (attempts that raise), dedupe (schema,
    messages, timeout) per call."""

    def __init__(self):
        super().__init__()
        self.conflicts = []
        self.drops = []
        self.dedupe_failures = 0
        self.dedupe = []

    def __call__(self, schema, messages, timeout):
        if kind(schema) != "dedupe":
            return super().__call__(schema, messages, timeout)
        with self.lock:
            self.dedupe.append((schema, [dict(m) for m in messages], timeout))
            attempt = len(self.dedupe)
        if attempt <= self.dedupe_failures:
            raise RuntimeError("dedupe boom")
        return dedupe_result(schema, self.drops)

    def draft(self, rows):
        self.outputs = {}
        for _, sec, problem, text, span, *ids in rows:
            self.outputs.setdefault((sec, problem), [(True, [])])[0][1].append(
                {"text": text, "evidence_span_ids": [span], "clinician_clarification_ids": ids[0] if ids else []})


@pytest.fixture
def model(monkeypatch):
    from core import llm
    m = Model()
    monkeypatch.setattr(llm, "parse", m)
    return m


def run(client, model):
    """Loads (and with conflicts, clarifies D01) to done. Returns (sid, the drafting part of the SSE)."""
    sid = create(client)
    sse = load(client, sid)
    if model.conflicts:
        assert sse[-1][0] == "conflicts_found", sse
        status, sse = submit(client, sid, [clarify()])
        assert status == 200
    assert sse[-1][0] == "done", sse
    return sid, sse


def final(client, sid, sse):
    draft = dict(sse)["draft"]["draft"]
    assert state(client, sid)["draft"] == draft  # the session holds the final, deduped snapshot
    return draft


def rows(draft):
    return [(c["claim_id"], c["section"], c["problem"], c["text"]) for c in draft["claims"]]


def kept(*dropped):
    """BASE without `dropped`, renumbered C01... contiguously in the same order."""
    left = [r for r in BASE if r[0] not in dropped]
    return [(f"C{i:02d}", sec, problem, text) for i, (_, sec, problem, text, _) in enumerate(left, 1)]


def removed(*ids):
    return [{"section": sec, "problem": problem, "text": text} for cid in ids for c, sec, problem, text, _ in BASE if c == cid]


def warns(sse):
    return dict(sse)["draft"]["warnings"]


def names_refused(warnings, cid, text):
    return any(cid in w or text in w for w in warnings)


def enum_of(schema):
    """The enum of the drop_claim_ids items in the JSON schema sent to the model."""
    js = schema.model_json_schema()
    items = js["properties"]["drop_claim_ids"]["items"]
    if "$ref" in items:
        items = js["$defs"][items["$ref"].split("/")[-1]]
    return items["enum"]


# ---------- schema ----------

@pytest.mark.parametrize("n", [3, 10])
def test_dedupe_schema_restricts_drop_ids_to_exactly_the_joined_claim_ids(client, model, n):
    model.draft(BASE[:n])
    run(client, model)

    (schema, _, timeout), = model.dedupe  # one dedupe call, after the join
    ids = [f"C{i:02d}" for i in range(1, n + 1)]
    assert sorted(enum_of(schema)) == ids  # built per call from the joined claims
    assert set(schema.model_json_schema()["properties"]) == {"drop_claim_ids"}  # no free-text fields
    assert schema.model_validate({"drop_claim_ids": ids[:2]}).drop_claim_ids == ids[:2]
    with pytest.raises(ValidationError):
        schema.model_validate({"drop_claim_ids": [f"C{n + 1:02d}"]})
    assert timeout == 35


# ---------- applying drops ----------

def test_listed_claims_are_removed_unknown_and_repeated_ids_ignored_and_the_rest_renumbered(client, model):
    model.draft(BASE)
    model.drops = ["C04", "C99", "bogus", "C04", "C09"]
    sid, sse = run(client, model)

    draft = final(client, sid, sse)
    assert rows(draft) == kept("C04", "C09")
    assert dict(sse)["dedupe_applied"] == {"count": 2, "removed": removed("C04", "C09")}
    by_text = {c["text"]: c for c in draft["claims"]}  # apart from the drops and IDs, claims are unchanged
    for _, _, _, text, span in BASE:
        if text in by_text:
            c = by_text[text]
            assert (c["evidence_span_ids"], c["clinician_clarification_ids"], c["support_status"]) == ([span], [], "unverified")


def test_empty_drop_list_leaves_the_joined_draft_unchanged(client, model):
    model.draft(BASE)
    sid, sse = run(client, model)

    assert len(model.dedupe) == 1
    draft = final(client, sid, sse)
    assert [(c["claim_id"], c["section"], c["problem"], c["text"], c["evidence_span_ids"], c["clinician_clarification_ids"],
             c["support_status"]) for c in draft["claims"]] == [(*r[:4], [r[4]], [], "unverified") for r in BASE]
    assert draft["discrepancies"] == [] and draft["status"] == "draft"
    assert warns(sse) == []
    assert dict(sse)["dedupe_applied"] == {"count": 0, "removed": []}


# ---------- guards ----------

def test_section_guard_keeps_the_last_claim_of_a_section_or_problem_group_in_drop_list_order(client, model):
    model.draft(BASE)
    # C10: follow_up's only claim; C05: the Hypertension group's only claim; C03 then C04: the whole Pneumonia group;
    # C01: reason_for_admission's only claim
    model.drops = ["C10", "C05", "C03", "C04", "C01"]
    sid, sse = run(client, model)

    assert rows(final(client, sid, sse)) == kept("C03")
    assert dict(sse)["dedupe_applied"] == {"count": 1, "removed": removed("C03")}
    for cid in ("C10", "C05", "C04", "C01"):
        assert names_refused(warns(sse), cid, TEXT[cid]), (cid, warns(sse))


@pytest.mark.parametrize("first, second", [("C03", "C05"), ("C05", "C03")])
def test_resolution_guard_keeps_the_last_claim_carrying_a_resolution(client, model, first, second):
    model.conflicts = [CONFLICT]
    # D01 is unmapped by the ticket 09 normalization stub, so it belongs to the Other hospital course group
    resolved = [
        ("C01", "reason_for_admission", None, "Admitted with pneumonia.", S1),
        ("C02", HC, "Pneumonia", "Started IV antibiotics.", S1),
        ("C03", HC, "Other", "Medication A dose clarified.", S1, ["D01"]),
        ("C04", HC, "Other", "Other course.", S2),
        ("C05", "discharge_medications", None, "Medication A 10 mg daily.", S3, ["D01"]),
        ("C06", "discharge_medications", None, "Oral Antibiotic B.", S1),
        ("C07", "follow_up", None, "Follow up with PCP in 1 week.", S3),
    ]
    model.draft(resolved)
    model.drops = [first, second]  # both carriers of D01: the first may go, the second is the last carrier
    sid, sse = run(client, model)

    draft = final(client, sid, sse)
    by_id = {r[0]: r for r in resolved}
    left = [r for r in resolved if r[0] != first]
    assert rows(draft) == [(f"C{i:02d}", r[1], r[2], r[3]) for i, r in enumerate(left, 1)]
    assert [c["text"] for c in draft["claims"] if "D01" in c["clinician_clarification_ids"]] == [by_id[second][3]]
    assert dict(sse)["dedupe_applied"] == {"count": 1, "removed": [
        {"section": by_id[first][1], "problem": by_id[first][2], "text": by_id[first][3]}]}
    refusals = [w for w in warns(sse) if second in w or by_id[second][3] in w]
    assert refusals and any("D01" in w or "resolution" in w.lower() for w in refusals), warns(sse)


# ---------- skipped call, failure ----------

@pytest.mark.parametrize("n", [0, 1])
def test_fewer_than_two_claims_makes_no_dedupe_call_and_reports_count_zero(client, model, n):
    model.draft(BASE[:n])
    sid, sse = run(client, model)

    assert model.dedupe == []
    assert dict(sse)["dedupe_applied"] == {"count": 0, "removed": []}
    assert rows(final(client, sid, sse)) == kept(*[r[0] for r in BASE[n:]])


@pytest.mark.parametrize("failures", [1, 2])
def test_dedupe_retries_once_then_keeps_all_claims_with_a_warning_and_the_load_completes(client, model, failures):
    model.draft(BASE)
    model.drops = ["C04"]
    model.dedupe_failures = failures
    sid, sse = run(client, model)  # dedupe never fails the load

    assert len(model.dedupe) == 2
    draft = final(client, sid, sse)
    if failures == 1:  # the retry answered
        assert rows(draft) == kept("C04")
        assert dict(sse)["dedupe_applied"]["count"] == 1
    else:
        assert rows(draft) == kept()
        assert dict(sse)["dedupe_applied"] == {"count": 0, "removed": []}
        assert warns(sse)


# ---------- SSE order ----------

def test_dedupe_applied_streams_after_the_section_events_and_before_draft_on_load_and_resume(client, model):
    model.draft(BASE)
    model.drops = ["C04"]
    sid, sse = run(client, model)
    names = [n for n, _ in sse]
    i = names.index("extraction_done") + 1
    assert set(names[i:i + N_SECTION_EVENTS]) <= set(SECTION_EVENTS)
    assert names[i + N_SECTION_EVENTS:] == ["dedupe_applied", "draft", "done"]
    assert dict(sse)["dedupe_applied"] == {"count": 1, "removed": removed("C04")}

    model.conflicts = [CONFLICT]  # resume: the stream after the conflict pause
    model.dedupe.clear()
    sid, sse = run(client, model)
    names = [n for n, _ in sse]
    assert set(names[:N_SECTION_EVENTS]) <= set(SECTION_EVENTS)
    assert names[N_SECTION_EVENTS:] == ["dedupe_applied", "draft", "done"]
    assert len(model.dedupe) == 1
    removed_ = dict(sse)["dedupe_applied"]["removed"]
    assert dict(sse)["dedupe_applied"]["count"] == len(removed_) == 1
    assert [c["text"] for c in final(client, sid, sse)["claims"]].count(TEXT["C04"]) == 1  # C06 has the same text



# ---------- live ----------

@pytest.mark.live
def test_live_dedupe_call_accepts_the_enum_schema_and_returns_only_existing_claim_ids(case_copy):
    assert case_copy.dedupe_calls, "no successful dedupe call"
    applied = dict(case_copy.sse)["dedupe_applied"]
    joined = [f"C{i:02d}" for i in range(1, len(case_copy.draft.claims) + applied["count"] + 1)]
    for schema, out in case_copy.dedupe_calls:
        assert sorted(enum_of(schema)) == joined
        assert set(out.drop_claim_ids) <= set(joined)


@pytest.mark.live
def test_case_001_after_dedupe_keeps_diagnoses_follow_up_problem_groups_and_the_resolution(case_copy):
    claims = case_copy.draft.claims
    assert {"discharge_diagnoses", "follow_up"} <= {c.section for c in claims}
    problems = {c.problem.lower() for c in claims if c.section == HC and c.problem}
    assert any("pneumonia" in p for p in problems), problems
    assert any("hypertension" in p for p in problems), problems
    assert any("D01" in c.clinician_clarification_ids for c in claims)
