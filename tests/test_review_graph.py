"""Specification tests for review questions (core/review_graph.py, spec §7.5 / §8)."""
from pathlib import Path

import pytest

from core import llm
from core import review_graph as rg

pytestmark = pytest.mark.live  # uses the model; run with: pytest -m live

ROOT = Path(__file__).parent.parent
CONFLICT = ["note_04_p01_b07", "note_05_p01_b04"]
RATIONALE_Q = "What was the reason for the Medication A dose change?"


@pytest.fixture
def case(monkeypatch, case_copy):
    monkeypatch.chdir(ROOT)
    return case_copy.draft, case_copy.spans, case_copy.events


@pytest.fixture
def stub(monkeypatch):
    """Replaces core.llm.parse; records each call's messages."""
    class Calls(list):
        span_ids = list(CONFLICT)  # what the stubbed model cites; tests may override
    calls = Calls()

    def fake(schema, messages, timeout):
        assert timeout == 35
        calls.append({"messages": messages})
        return rg.Answer(answer="x", span_ids=calls.span_ids)

    monkeypatch.setattr(llm, "parse", fake)
    return calls


def prompt(call):
    return "\n".join(m["content"] for m in call["messages"])


def test_graph_is_compiled_langgraph():
    assert hasattr(rg.graph, "invoke")


@pytest.mark.parametrize("question", ["Why do the notes mention different doses?", RATIONALE_Q])
def test_conflict_question_retrieves_both_conflict_spans(case, stub, question):  # T04
    draft, spans, events = case
    before = draft.discrepancies[0].status
    out = rg.ask(question, draft, spans, events)
    assert out["intent"] == "question"
    assert set(CONFLICT) <= set(out["retrieved"])
    assert len(stub) == 1 and all(sid in prompt(stub[0]) for sid in CONFLICT)
    assert draft.discrepancies[0].status == before  # asking never changes a discrepancy


def test_marker_question_is_direct_lookup(case, stub):
    draft, spans, events = case
    out = rg.ask("What does [N04:B07] say?", draft, spans, events)
    assert out["retrieved"] == ["note_04_p01_b07"]


def test_cited_ids_not_retrieved_are_dropped(case, stub):  # T12
    draft, spans, events = case
    stub.span_ids = ["note_04_p01_b07", "bogus"]
    out = rg.ask("What does [N04:B07] say?", draft, spans, events)
    assert out["cited"] == ["note_04_p01_b07"]


def test_answer_retries_once_on_transient_error_only(case, monkeypatch):
    import httpx
    import openai
    draft, spans, events = case
    calls = []

    def flaky(schema, messages, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://x"))
        return rg.Answer(answer="x", span_ids=[])

    monkeypatch.setattr(llm, "parse", flaky)
    assert rg.ask("What was given on day 1?", draft, spans, events)["answer"] == "x" and len(calls) == 2

    def broken(schema, messages, timeout):
        calls.append(1)
        raise RuntimeError("not transient")

    calls.clear()
    monkeypatch.setattr(llm, "parse", broken)
    with pytest.raises(RuntimeError):
        rg.ask("What was given on day 1?", draft, spans, events)
    assert len(calls) == 1


def test_read_section_uses_draft_without_llm(case, stub):
    draft, spans, events = case
    out = rg.ask("Read the condition at discharge", draft, spans, events)
    claims = [c for c in draft.claims if c.section == "condition_at_discharge"]
    assert out["intent"] == "read_section" and claims and all(c.text in out["answer"] for c in claims)
    assert out["cited"] == [s for c in claims for s in c.evidence_span_ids] and stub == []


def test_one_word_is_unknown_without_llm(case, stub):
    draft, spans, events = case
    out = rg.ask("hi", draft, spans, events)
    assert out["intent"] == "unknown" and out["cited"] == [] and stub == []


def test_question_sends_all_passages(case, stub):  # no keyword retrieval: synonyms like "client" still work
    draft, spans, events = case
    out = rg.ask("what was the clients condition?", draft, spans, events)
    assert out["retrieved"] == list(spans) and len(stub) == 1


def test_ask_does_not_mutate_draft(case, stub):
    draft, spans, events = case
    before = draft.model_dump()
    rg.ask("Why do the notes mention different doses?", draft, spans, events)
    rg.ask("Read the condition at discharge", draft, spans, events)
    assert draft.model_dump() == before


def test_rationale_live(case):  # T05
    draft, spans, events = case
    out = rg.ask(RATIONALE_Q, draft, spans, events)
    assert rg.NOT_ESTABLISHED in out["answer"]
    assert set(out["cited"]) <= set(out["retrieved"])
    assert not any(w in out["answer"].lower() for w in ("because", "due to", "in order to", "titrat"))


# --- Review fixes (tier-c) ---
OXYGEN_Q = "When was supplemental oxygen discontinued?"


def user_msg(call):
    return next(m["content"] for m in call["messages"] if m["role"] == "user")


def system_msg(call):
    return next(m["content"] for m in call["messages"] if m["role"] == "system")


def test_conflict_prompt_flags_discrepancy(case, stub):
    draft, spans, events = case
    rg.ask(RATIONALE_Q, draft, spans, events)
    assert len(stub) == 1
    assert "Flagged for review" in user_msg(stub[0])
    assert draft.discrepancies[0].description in user_msg(stub[0])
    assert "cite every such passage" in system_msg(stub[0])


def test_oxygen_question_still_retrieves(case, stub):
    draft, spans, events = case
    assert "note_04_p01_b09" in rg.ask(OXYGEN_Q, draft, spans, events)["retrieved"]


def test_rationale_live_cites_conflict(case):
    draft, spans, events = case
    out = rg.ask(RATIONALE_Q, draft, spans, events)
    assert set(CONFLICT) <= set(out["cited"])


@pytest.mark.parametrize("question", ["Why do the notes mention different doses?", RATIONALE_Q])
def test_conflict_answers_attribute_flag_to_app_and_hide_ids(case, question):  # review M1 + opt 1
    draft, spans, events = case
    out = rg.ask(question, draft, spans, events)
    assert set(CONFLICT) <= set(out["cited"])
    assert "notes flag" not in out["answer"].lower()
    assert "note_0" not in out["answer"]


def test_passages_carry_note_dates(case, stub):  # review opt 2
    draft, spans, events = case
    rg.ask(RATIONALE_Q, draft, spans, events)
    assert "(note dated 2026-03-04 (Hospital Day 3))" in user_msg(stub[0])


def test_first_question_sends_no_history(case, stub):
    draft, spans, events = case
    rg.ask("Why do the notes mention different doses?", draft, spans, events, thread_id="t-first")
    assert [m["role"] for m in stub[0]["messages"]] == ["system", "user"]


def test_follow_up_sends_last_three_turns(case, stub):
    draft, spans, events = case
    qs = ["What was given on day 1?", "Read the condition at discharge", "What about day 2?",
          "And day 3?", "And day 4?"]
    for q in qs:
        rg.ask(q, draft, spans, events, thread_id="t-hist")
    last = stub[-1]["messages"]  # 4 LLM calls; read_section has none but is still a turn
    users = [m["content"] for m in last if m["role"] == "user"]
    assert users[:-1] == qs[1:4] and qs[4] in users[-1]  # turns 2-4 (incl. read section), then the new question
    assert "Earlier answers are not evidence" in last[1]["content"]
    rg.ask("What was given on day 1?", draft, spans, events, thread_id="t-other")
    assert [m["role"] for m in stub[-1]["messages"]] == ["system", "user"]  # threads don't share history
