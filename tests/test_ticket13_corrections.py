"""Specification tests for ticket 13 (model-proposed corrections), through TestClient.

The model is stubbed at core.llm.parse: the `proposer` fixture answers the correction call and hands every other call
to the `calls` stub of tests/test_api.py (so loads run as before).

Test-imposed assumptions (the contract leaves these open):
- The correction call is recognized by a schema with an `after` field (contract: `CorrectionResult { after: str }`).
  Stub answers are built with model_construct, so a blank `after` reaches the code even if the schema forbids it.
- Prompt content is checked only by substring: the statement, the claim's section and text, and each cited passage's
  span ID and text appear somewhere in the call's message contents.
- "The error fed back" on a blank/unchanged retry: the retry call's messages start with the first call's messages and
  add at least one more (as in the extraction/section/conflict retry loops). For an exception, only the retry is required
  (the other loops re-send the same messages after an exception).
"""
import re
import threading

import pytest
from fastapi.testclient import TestClient

from api import sessions
from core import llm
from core.models import Draft, SummaryClaim
from tests.test_api import calls, client, create, load, state  # noqa: F401  (fixtures)

PREFIX = "/api/sessions"
WAIT = 10
AFTER = "Medication A 5 mg daily, increased to 10 mg daily from Day 3."
STATEMENT = "Dose was 10 mg from Day 3."
MED_SPANS = ["note_03_p01_b07", "note_04_p01_b07"]  # cited by C01; case_001 spans
CLAIMS = [
    SummaryClaim(claim_id="C01", section="discharge_medications", text="Medication A 5 mg daily.",
                 evidence_span_ids=MED_SPANS, support_status="needs_review"),
    SummaryClaim(claim_id="C02", section="reason_for_admission", text="Admitted with community-acquired pneumonia.",
                 evidence_span_ids=["note_01_p01_b10"], support_status="supported"),
]


@pytest.fixture
def proposer(calls, monkeypatch):
    """Answers correction calls (schema with an `after` field) and records them as {messages, timeout}.
    answers: queue of str (the proposed `after`) or Exception (raised); empty queue -> `after`.
    during: optional callback run inside each correction call."""
    class Proposer(list):
        after = AFTER
        during = None
    rec, inner = Proposer(), llm.parse
    rec.answers = []

    def parse(schema, messages, timeout):
        if "after" not in schema.model_fields:
            return inner(schema, messages, timeout)
        rec.append({"messages": messages, "timeout": timeout})
        if rec.during:
            rec.during()
        answer = rec.answers.pop(0) if rec.answers else rec.after
        if isinstance(answer, Exception):
            raise answer
        return schema.model_construct(after=answer)

    monkeypatch.setattr(llm, "parse", parse)
    return rec


def ready(client):
    """A loaded case_001 session whose draft is CLAIMS (C01 cites two passages from different notes)."""
    sid = create(client)
    assert load(client, sid)[-1][0] == "done"
    sessions.update(sid, draft=Draft(claims=CLAIMS))
    return sid


def propose(client, sid, cid="C01", statement=STATEMENT):
    return client.post(f"{PREFIX}/{sid}/corrections", json={"claim_id": cid, "statement": statement})


def text_of(call) -> str:
    return "\n".join(str(m["content"]) for m in call["messages"])


def assert_fed_back(first, retry):
    """The retry repeats the first call's messages and adds the feedback after them."""
    assert len(retry["messages"]) > len(first["messages"])
    assert retry["messages"][:len(first["messages"])] == first["messages"]


# --- the model call -------------------------------------------------------------------------------------------

def test_one_call_carries_statement_claim_and_each_cited_passage(client, proposer):
    sid = ready(client)
    assert propose(client, sid).status_code == 201
    (call,) = proposer
    text, passages = text_of(call), state(client, sid)["passages"]
    assert STATEMENT in text
    assert CLAIMS[0].text in text and CLAIMS[0].section in text
    for span_id in MED_SPANS:
        assert span_id in text and passages[span_id]["text"] in text
    assert call["timeout"] == 20


def test_no_uncited_passage_reaches_the_call(client, proposer):
    sid = ready(client)
    assert propose(client, sid).status_code == 201
    (call,) = proposer
    text, passages = text_of(call), state(client, sid)["passages"]
    allowed = "\n".join([STATEMENT, CLAIMS[0].text, *(passages[s]["text"] for s in MED_SPANS)])
    for span_id, p in passages.items():
        if span_id in MED_SPANS:
            continue
        assert not re.search(rf"\b{re.escape(span_id)}\b", text), f"uncited span {span_id} reached the call"
        if p["text"] not in allowed:  # identical text of a cited passage may legitimately appear
            assert p["text"] not in text, f"uncited passage {span_id} reached the call"


def test_model_result_becomes_the_pending_revision(client, proposer):
    sid = ready(client)
    r = propose(client, sid)
    assert r.status_code == 201
    rev, clar = r.json()["revision"], r.json()["clarification"]
    assert rev == {"revision_id": "R01", "target_claim_id": "C01", "before": CLAIMS[0].text, "after": AFTER,
                   "clinician_statement": STATEMENT, "clarification_id": "K01", "source_span_ids": MED_SPANS,
                   "status": "pending"}
    assert clar == {"clarification_id": "K01", "statement": STATEMENT, "target_claim_id": "C01", "status": "pending"}
    s = state(client, sid)
    assert s["pending"] == {"revision": rev, "clarification": clar}
    assert s["draft"] == Draft(claims=CLAIMS).model_dump(mode="json")  # nothing changes before accept


def test_client_supplied_after_is_not_used(client, proposer):
    sid = ready(client)
    r = client.post(f"{PREFIX}/{sid}/corrections", json={"claim_id": "C01", "statement": STATEMENT, "after": "Typed text."})
    assert r.status_code == 422 or r.json()["revision"]["after"] == AFTER  # rejected, or ignored in favour of the model


# --- retries and failures -------------------------------------------------------------------------------------

@pytest.mark.parametrize("first", ["", "   ", f"  {CLAIMS[0].text}\n"], ids=["empty", "blank", "unchanged"])
def test_blank_or_unchanged_result_is_retried_with_feedback(client, proposer, first):
    sid = ready(client)
    proposer.answers = [first, AFTER]
    r = propose(client, sid)
    assert r.status_code == 201 and r.json()["revision"]["after"] == AFTER
    assert len(proposer) == 2
    assert_fed_back(*proposer)


def test_exception_is_retried_once(client, proposer):
    sid = ready(client)
    proposer.answers = [RuntimeError("boom"), AFTER]
    r = propose(client, sid)
    assert r.status_code == 201 and r.json()["revision"]["after"] == AFTER
    assert len(proposer) == 2 and STATEMENT in text_of(proposer[1])


@pytest.mark.parametrize("answers", [["", "  "], [CLAIMS[0].text, f" {CLAIMS[0].text} "]], ids=["blank", "unchanged"])
def test_still_unchanged_after_retry_422_and_nothing_pending(client, proposer, answers):
    sid = ready(client)
    proposer.answers = list(answers)
    r = propose(client, sid)
    assert r.status_code == 422 and r.json() == {"detail": "the statement did not change the claim"}
    assert len(proposer) == 2
    assert state(client, sid)["pending"] is None
    later = propose(client, sid)
    assert later.status_code == 201 and later.json()["revision"]["revision_id"] == "R01"


def test_two_exceptions_502_and_nothing_pending(client, proposer):
    sid = ready(client)
    proposer.answers = [RuntimeError("boom"), RuntimeError("boom again")]
    r = propose(client, sid)
    assert r.status_code == 502 and r.json()["detail"].startswith("correction failed: ")
    assert len(proposer) == 2
    assert state(client, sid)["pending"] is None
    later = propose(client, sid)
    assert later.status_code == 201 and later.json()["revision"]["revision_id"] == "R01"


# --- validation (no model call) -------------------------------------------------------------------------------

@pytest.mark.parametrize("statement", ["", "   "])
def test_blank_statement_422_without_model_call(client, proposer, statement):
    sid = ready(client)
    assert propose(client, sid, statement=statement).status_code == 422
    assert proposer == [] and state(client, sid)["pending"] is None


def test_unknown_session_and_claim_404_without_model_call(client, proposer):
    assert propose(client, "nope").status_code == 404
    sid = ready(client)
    assert propose(client, sid, cid="C99").status_code == 404
    assert proposer == [] and state(client, sid)["pending"] is None


def test_409_cases_without_model_call(client, proposer):
    never_loaded = create(client)
    r = propose(client, never_loaded)
    assert r.status_code == 409 and r.json() == {"detail": "no draft"}
    sid = ready(client)
    first = propose(client, sid).json()
    assert propose(client, sid, cid="C02").status_code == 409  # a correction already pending
    assert state(client, sid)["pending"] == first
    sessions.update(sid, load_running=True)
    r = propose(client, sid)
    assert r.status_code == 409 and r.json() == {"detail": "load running"}
    assert len(proposer) == 1  # only the first, successful proposal called the model


# --- the session lock is not held during the model call -------------------------------------------------------

def hold_model(proposer):
    """Blocks the correction call until released; returns (entered, release)."""
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        release.wait(WAIT)
    proposer.during = hold
    return entered, release


def in_thread(fn):
    out = []
    t = threading.Thread(target=lambda: out.append(fn()))
    t.start()
    return t, out


def test_other_session_is_readable_while_the_model_call_runs(client, proposer):
    sid, other = ready(client), ready(client)
    entered, release = hold_model(proposer)
    t, proposed = in_thread(lambda: propose(TestClient(client.app), sid))
    try:
        assert entered.wait(WAIT), "the proposal never reached the model call"
        g, got = in_thread(lambda: TestClient(client.app).get(f"{PREFIX}/{other}").status_code)
        g.join(WAIT)
        assert got == [200], "another session's GET blocked while the correction call was in flight"
    finally:
        release.set()
        t.join(WAIT)
    assert proposed[0].status_code == 201


def test_load_started_during_the_model_call_makes_the_proposal_409(client, proposer):
    sid = ready(client)
    entered, release = hold_model(proposer)
    t, proposed = in_thread(lambda: propose(TestClient(client.app), sid))
    try:
        assert entered.wait(WAIT), "the proposal never reached the model call"
        lt, loaded = in_thread(lambda: load(TestClient(client.app), sid))
        lt.join(WAIT)
        assert loaded and loaded[0][-1][0] == "done", "a load on the same session blocked while the correction call was in flight"
    finally:
        release.set()
        t.join(WAIT)
    assert proposed[0].status_code == 409
    s = state(client, sid)
    assert s["pending"] is None and s["revisions"] == []


# --- live -----------------------------------------------------------------------------------------------------

LIVE_STATEMENT = "Follow-up with the primary care clinic within 7 days of discharge."


@pytest.mark.live
def test_live_case_001_follow_up_correction(client):
    sid = create(client)
    assert load(client, sid)[-1][0] == "done"
    claim = next(c for c in state(client, sid)["draft"]["claims"] if c["section"] == "follow_up")
    r = propose(client, sid, cid=claim["claim_id"], statement=LIVE_STATEMENT)
    assert r.status_code == 201, r.text
    rev = r.json()["revision"]
    print(f"\nbefore: {rev['before']}\nafter:  {rev['after']}")
    assert rev["after"].strip() != rev["before"].strip() and "7 days" in rev["after"]
    s = client.post(f"{PREFIX}/{sid}/corrections/{rev['revision_id']}/accept").json()
    assert next(c for c in s["draft"]["claims"] if c["claim_id"] == claim["claim_id"])["text"] == rev["after"]
