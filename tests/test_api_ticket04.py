"""Specification tests for ticket 04 (review features + editing lock), through TestClient.

Setup: a real load with the model stubbed at core.llm.parse (`calls` fixture), so documents, spans and the
draft are the app's own. The draft then gets one discrepancy via api.sessions.update (the stub summarizer
produces none). Ask is stubbed by monkeypatching the `ask` name in api.app, so api/app.py must call it as a
module global: `from core.review_graph import ask`.

Ticket 13: the corrected text comes from a model call, so propose posts {claim_id, statement} and the stubbed model
(the `proposer` fixture of tests/test_ticket13_corrections.py, autouse here) answers with the `after` the helper names.
"""
import pytest

import api.app
from api import sessions
from core.models import Discrepancy, Draft
from tests.test_api import calls, client, create, load, state  # noqa: F401  (fixtures)
from tests.test_ticket13_corrections import proposer  # noqa: F401  (fixture)

PREFIX = "/api/sessions"
SYNTHETIC = "SYNTHETIC DEMONSTRATION — NOT FOR CLINICAL USE"


def loaded(client, case_id="case_001"):
    """Session after a successful load; its draft carries discrepancy D01 citing the first claim's spans."""
    sid = create(client, case_id)
    assert [e for e, _ in load(client, sid)][-1] == "done"
    draft = Draft.model_validate(state(client, sid)["draft"])
    d = Discrepancy(discrepancy_id="D01", description="Route of antibiotic differs between notes.",
                    source_span_ids=draft.claims[0].evidence_span_ids)
    sessions.update(sid, draft=draft.model_copy(update={"discrepancies": [d]}))
    return sid


def claim_id(client, sid):
    return state(client, sid)["draft"]["claims"][0]["claim_id"]


PROPOSER = None  # the current test's model stub (ticket 13)


@pytest.fixture(autouse=True)
def model_proposes(proposer):
    global PROPOSER
    PROPOSER = proposer


def propose(client, sid, cid, after="Admitted for right lower lobe pneumonia.", statement="It was the right lobe."):
    """`after` is what the stubbed model proposes (ticket 13)."""
    PROPOSER.after = after
    return client.post(f"{PREFIX}/{sid}/corrections", json={"claim_id": cid, "statement": statement})


def approve(client, sid, reviewer="Dr Test"):
    return client.post(f"{PREFIX}/{sid}/approve", json={"reviewer": reviewer})


@pytest.fixture
def asked(monkeypatch):
    """Replaces api.app.ask; records each call. Set asked.fail to make it raise."""
    class Asked(list):
        fail = False
    rec = Asked()

    def fake_ask(question, draft, spans, events=(), thread_id=None):
        rec.append({"question": question, "draft": draft, "spans": spans, "events": list(events), "thread_id": thread_id})
        if rec.fail:
            raise RuntimeError("boom")
        sid = next(iter(spans))
        return {"question": question, "draft": draft, "spans": spans, "intent": "question",
                "retrieved": list(spans), "answer": "Antibiotic B was started.", "cited": [sid],
                "turns": [{"q": question, "a": "Antibiotic B was started."}]}

    monkeypatch.setattr(api.app, "ask", fake_ask, raising=False)
    return rec


# Every operation as (method, path suffix, json body); accept/reject name R01, the first revision id.
OPERATIONS = {
    "ask": ("post", "/ask", {"question": "Which antibiotic was started?"}),
    "propose": ("post", "/corrections", {"claim_id": "C01", "statement": "y"}),
    "accept": ("post", "/corrections/R01/accept", None),
    "reject": ("post", "/corrections/R01/reject", None),
    "approve": ("post", "/approve", {"reviewer": "Dr Test"}),
    "export": ("get", "/export", None),
}


def call(client, sid, op):
    method, suffix, body = OPERATIONS[op]
    return getattr(client, method)(f"{PREFIX}/{sid}{suffix}", **({"json": body} if body is not None else {}))


# --- shared checks: 404 -> 409 load running -> 409 no draft ---------------------------------------------------

@pytest.mark.parametrize("op", OPERATIONS)
def test_unknown_session_404(client, asked, op):
    assert call(client, "nope", op).status_code == 404


@pytest.mark.parametrize("op", OPERATIONS)
def test_409_while_load_running(client, calls, asked, op):
    sid = loaded(client)
    propose(client, sid, claim_id(client, sid))  # R01 pending, so accept/reject would otherwise succeed
    sessions.update(sid, load_running=True)
    r = call(client, sid, op)
    assert r.status_code == 409 and r.json() == {"detail": "load running"}
    assert asked == []


@pytest.mark.parametrize("op", OPERATIONS)
def test_409_without_draft(client, asked, op):
    sid = create(client)  # never loaded
    r = call(client, sid, op)
    assert r.status_code == 409 and r.json() == {"detail": "no draft"}
    assert asked == []


def test_new_session_has_no_corrections(client):
    s = state(client, create(client))
    assert s["revisions"] == [] and s["clarifications"] == [] and s["pending"] is None


# --- ask ------------------------------------------------------------------------------------------------------

def test_ask_returns_intent_answer_cited_and_uses_session_thread(client, calls, asked):
    sid = loaded(client)
    s = state(client, sid)
    r = client.post(f"{PREFIX}/{sid}/ask", json={"question": "Which antibiotic was started?"})
    assert r.status_code == 200
    (got,) = asked
    assert r.json() == {"intent": "question", "answer": "Antibiotic B was started.", "cited": [next(iter(s["passages"]))]}
    assert got["question"] == "Which antibiotic was started?"
    assert got["draft"].model_dump(mode="json") == s["draft"]
    assert set(got["spans"]) == set(s["passages"])
    assert [e.model_dump(mode="json") for e in got["events"]] == s["events"]
    assert got["thread_id"] == s["chat_thread_id"]


def test_two_sessions_ask_on_different_threads(client, calls, asked):
    a, b = loaded(client), loaded(client)
    for sid in (a, a, b):
        assert client.post(f"{PREFIX}/{sid}/ask", json={"question": "What happened?"}).status_code == 200
    ta, ta2, tb = (c["thread_id"] for c in asked)
    assert ta == ta2 == state(client, a)["chat_thread_id"]
    assert tb == state(client, b)["chat_thread_id"] and ta != tb


@pytest.mark.parametrize("question", ["", "   "])
def test_ask_blank_question_422(client, calls, asked, question):
    sid = loaded(client)
    assert client.post(f"{PREFIX}/{sid}/ask", json={"question": question}).status_code == 422
    assert asked == []


def test_ask_failure_502_with_type_and_message(client, calls, asked):
    sid = loaded(client)
    asked.fail = True
    r = client.post(f"{PREFIX}/{sid}/ask", json={"question": "What happened?"})
    assert r.status_code == 502 and r.json() == {"detail": "RuntimeError: boom"}


# --- corrections ----------------------------------------------------------------------------------------------

def test_propose_returns_pending_pair_and_leaves_draft_unchanged(client, calls):
    sid = loaded(client)
    before = state(client, sid)
    cid = before["draft"]["claims"][0]["claim_id"]
    r = propose(client, sid, cid)
    assert r.status_code == 201
    rev, clar = r.json()["revision"], r.json()["clarification"]
    assert rev["revision_id"] == "R01" and rev["target_claim_id"] == cid and rev["status"] == "pending"
    assert rev["before"] == before["draft"]["claims"][0]["text"]
    assert rev["after"] == "Admitted for right lower lobe pneumonia."
    assert rev["clinician_statement"] == "It was the right lobe." and rev["clarification_id"] == "K01"
    assert clar == {"clarification_id": "K01", "statement": "It was the right lobe.", "target_claim_id": cid,
                    "status": "pending"}
    s = state(client, sid)
    assert s["pending"] == {"revision": rev, "clarification": clar}
    assert s["draft"] == before["draft"] and s["revisions"] == [] and s["clarifications"] == []


def test_propose_unknown_claim_404(client, calls):
    sid = loaded(client)
    assert propose(client, sid, "no_such_claim").status_code == 404
    assert state(client, sid)["pending"] is None


def test_second_propose_while_pending_409(client, calls):
    sid = loaded(client)
    cid = claim_id(client, sid)
    first = propose(client, sid, cid).json()
    assert propose(client, sid, cid, after="Other text.").status_code == 409
    assert state(client, sid)["pending"] == first


def test_accept_updates_text_links_clarification_and_resets_approval(client, calls):
    sid = loaded(client)
    cid = claim_id(client, sid)
    assert approve(client, sid).status_code == 200
    rev = propose(client, sid, cid).json()["revision"]
    r = client.post(f"{PREFIX}/{sid}/corrections/{rev['revision_id']}/accept")
    assert r.status_code == 200
    s = state(client, sid)
    assert r.json() == s
    claim = next(c for c in s["draft"]["claims"] if c["claim_id"] == cid)
    assert claim["text"] == "Admitted for right lower lobe pneumonia."
    assert claim["clinician_clarification_ids"] == ["K01"]
    assert s["draft"]["status"] == "draft" and s["draft"]["approved_at"] is None and s["draft"]["reviewer"] is None
    assert [(x["revision_id"], x["status"]) for x in s["revisions"]] == [("R01", "accepted")]
    assert [(x["clarification_id"], x["status"]) for x in s["clarifications"]] == [("K01", "accepted")]
    assert s["pending"] is None
    nxt = propose(client, sid, cid, after="Third text.").json()  # numbering continues
    assert nxt["revision"]["revision_id"] == "R02" and nxt["clarification"]["clarification_id"] == "K02"


def test_reject_leaves_draft_unchanged(client, calls):
    sid = loaded(client)
    before = state(client, sid)["draft"]
    propose(client, sid, before["claims"][0]["claim_id"])
    r = client.post(f"{PREFIX}/{sid}/corrections/R01/reject")
    assert r.status_code == 200
    s = state(client, sid)
    assert r.json() == s and s["draft"] == before and s["pending"] is None
    assert [(x["revision_id"], x["status"]) for x in s["revisions"]] == [("R01", "rejected")]
    assert [(x["clarification_id"], x["status"]) for x in s["clarifications"]] == [("K01", "rejected")]


@pytest.mark.parametrize("action", ["accept", "reject"])
def test_accept_or_reject_non_pending_revision_404(client, calls, action):
    sid = loaded(client)
    assert client.post(f"{PREFIX}/{sid}/corrections/R01/{action}").status_code == 404  # nothing pending
    propose(client, sid, claim_id(client, sid))
    assert client.post(f"{PREFIX}/{sid}/corrections/R99/{action}").status_code == 404
    assert state(client, sid)["pending"]["revision"]["revision_id"] == "R01"


# --- approve and export ---------------------------------------------------------------------------------------

def test_approve_sets_status_time_and_reviewer(client, calls):
    sid = loaded(client)
    r = approve(client, sid, "Simulated resident (demo)")
    assert r.status_code == 200
    s = state(client, sid)
    assert r.json() == s
    assert s["draft"]["status"] == "approved" and s["draft"]["reviewer"] == "Simulated resident (demo)"
    assert s["draft"]["approved_at"]


@pytest.mark.parametrize("reviewer", ["", "   "])
def test_approve_blank_reviewer_422(client, calls, reviewer):
    sid = loaded(client)
    assert approve(client, sid, reviewer).status_code == 422
    assert state(client, sid)["draft"]["status"] == "draft"


def test_approve_while_correction_pending_409(client, calls):
    sid = loaded(client)
    propose(client, sid, claim_id(client, sid))
    assert approve(client, sid).status_code == 409
    assert state(client, sid)["draft"]["status"] == "draft"


def test_export_before_approval_409(client, calls):
    sid = loaded(client)
    assert client.get(f"{PREFIX}/{sid}/export").status_code == 409


def test_export_after_approval_is_markdown_attachment(client, calls):
    sid = loaded(client)
    cid = claim_id(client, sid)
    propose(client, sid, cid)
    client.post(f"{PREFIX}/{sid}/corrections/R01/accept")
    approve(client, sid)
    r = client.get(f"{PREFIX}/{sid}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["content-disposition"] == 'attachment; filename="discharge_summary_case_001.md"'
    md = r.text
    assert SYNTHETIC in md and "APPROVED by Dr Test" in md
    assert "## Unresolved discrepancies" in md and "D01" in md and "Route of antibiotic differs between notes." in md
    assert f'K01 → {cid}: "It was the right lobe."' in md
    assert "## Source appendix" in md


# --- reload invariant -----------------------------------------------------------------------------------------

def test_new_load_clears_corrections_and_keeps_chat_thread(client, calls):
    sid = loaded(client)
    cid = claim_id(client, sid)
    propose(client, sid, cid)
    client.post(f"{PREFIX}/{sid}/corrections/R01/accept")
    propose(client, sid, cid, after="Pending text.")
    old = state(client, sid)
    assert old["revisions"] and old["clarifications"] and old["pending"]

    assert [e for e, _ in load(client, sid)][-1] == "done"
    s = state(client, sid)
    assert s["revisions"] == [] and s["clarifications"] == [] and s["pending"] is None
    assert s["chat_thread_id"] == old["chat_thread_id"]  # kept across reloads of the same session (03a)
    assert propose(client, sid, claim_id(client, sid)).json()["revision"]["revision_id"] == "R01"
