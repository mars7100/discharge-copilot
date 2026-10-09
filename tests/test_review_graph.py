"""Specification tests for review questions (core/review_graph.py, spec §7.5 / §8)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import llm
from core import review_graph as rg
from core.extract import extract_events
from core.ingest import ingest_dir
from core.summarize import generate_draft

ROOT = Path(__file__).parent.parent
CONFLICT = ["note_04_p01_b07", "note_05_p01_b04"]
RATIONALE_Q = "What was the reason for the Medication A dose change?"


@pytest.fixture
def case(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.delenv("LLM_RECORD_DIR", raising=False)
    docs, spans, _ = ingest_dir(ROOT / "fixtures" / "case_001")
    events, _ = extract_events(docs, spans)
    draft, _ = generate_draft(events, spans)
    return draft, spans, events


@pytest.fixture
def stub(monkeypatch):
    """Replaces core.llm.parse; records each call's messages and mode."""
    class Calls(list):
        span_ids = list(CONFLICT)  # what the stubbed model cites; tests may override
    calls = Calls()

    def fake(schema, messages, mode=None):
        calls.append({"messages": messages, "mode": mode})
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
    out = rg.ask(question, draft, spans, events)
    assert out["intent"] == "question"
    assert set(CONFLICT) <= set(out["retrieved"]) and len(out["retrieved"]) <= 8
    assert len(stub) == 1 and all(sid in prompt(stub[0]) for sid in CONFLICT)
    assert draft.discrepancies[0].status == "open"


def test_marker_question_is_direct_lookup(case, stub):
    draft, spans, events = case
    out = rg.ask("What does [N04:B07] say?", draft, spans, events)
    assert out["retrieved"] == ["note_04_p01_b07"]


def test_cited_ids_not_retrieved_are_dropped(case, stub):  # T12
    draft, spans, events = case
    stub.span_ids = ["note_04_p01_b07", "bogus"]
    out = rg.ask("What does [N04:B07] say?", draft, spans, events)
    assert out["cited"] == ["note_04_p01_b07"]


def test_read_section_uses_draft_without_llm(case, stub):
    draft, spans, events = case
    out = rg.ask("Read the condition at discharge", draft, spans, events)
    claim = next(c for c in draft.claims if c.section == "condition_at_discharge")
    assert out["intent"] == "read_section" and claim.text in out["answer"]
    assert out["cited"] == claim.evidence_span_ids and stub == []


def test_one_word_is_unknown_without_llm(case, stub):
    draft, spans, events = case
    out = rg.ask("hi", draft, spans, events)
    assert out["intent"] == "unknown" and out["cited"] == [] and stub == []


def test_no_retrieval_match_is_not_established_without_llm(case, stub):
    draft, spans, events = case
    out = rg.ask("zzzz qqqq", draft, spans, events)
    assert out["answer"] == rg.NOT_ESTABLISHED and out["cited"] == [] and stub == []


def test_missing_recording_falls_back_to_live(case, monkeypatch):
    draft, spans, events = case
    modes = []

    def fake(schema, messages, mode=None):
        modes.append(mode)
        if mode != "live":
            raise FileNotFoundError("no recording")
        return rg.Answer(answer="answered", span_ids=["note_04_p01_b07"])

    monkeypatch.setattr(llm, "parse", fake)
    out = rg.ask("What does [N04:B07] say?", draft, spans, events)
    assert out["answer"] == "answered" and modes[-1] == "live" and len(modes) == 2


def test_ask_does_not_mutate_draft(case, stub):
    draft, spans, events = case
    before = draft.model_dump()
    rg.ask("Why do the notes mention different doses?", draft, spans, events)
    rg.ask("Read the condition at discharge", draft, spans, events)
    assert draft.model_dump() == before


def test_rationale_replay(case, monkeypatch):  # T05: needs a committed replay recording
    draft, spans, events = case
    monkeypatch.setattr(llm, "_call", lambda *a, **k: pytest.fail("no replay recording for the rationale question"))
    out = rg.ask(RATIONALE_Q, draft, spans, events)
    assert rg.NOT_ESTABLISHED in out["answer"]
    assert set(out["cited"]) <= set(out["retrieved"])
    assert not any(w in out["answer"].lower() for w in ("because", "due to", "in order to", "titrat"))


def test_app_ask_read_section(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("LLM_MODE", "replay")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.sidebar.button[0].click().run()  # Load sample case
    boxes = [t for t in at.text_input if t.label == "Ask about the notes"]
    assert boxes, "no text_input labelled 'Ask about the notes'"
    boxes[0].set_value("Read the condition at discharge")
    asks = [b for b in at.button if b.label == "Ask"]
    assert asks, "no button labelled 'Ask'"
    asks[0].click().run()
    claim = next(c for c in at.session_state["draft"].claims if c.section == "condition_at_discharge")
    assert not at.exception and any(claim.text in m.value for m in at.markdown)


# --- Review fixes (tier-c) ---
from core.models import Draft  # noqa: E402

OXYGEN_Q = "When was supplemental oxygen discontinued?"


def user_msg(call):
    return next(m["content"] for m in call["messages"] if m["role"] == "user")


def system_msg(call):
    return next(m["content"] for m in call["messages"] if m["role"] == "system")


def app_loaded(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("LLM_MODE", "replay")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.sidebar.button[0].click().run()  # Load sample case
    return at


def app_ask(at, question):
    next(t for t in at.text_input if t.label == "Ask about the notes").set_value(question)
    next(b for b in at.button if b.label == "Ask").click().run()
    return at


def test_app_duplicate_citations_do_not_crash(monkeypatch):
    at = app_ask(app_loaded(monkeypatch), "Read the Follow-up")
    assert not at.exception, at.exception
    app_ask(at, "Read the condition at discharge")
    assert not at.exception, at.exception


def test_app_failed_question_shows_error_and_keeps_rendering(monkeypatch):
    at = app_loaded(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(llm, "parse", boom)  # after load: extraction/summary already done
    app_ask(at, "Why do the notes mention different doses?")
    assert not at.exception, at.exception
    assert any("Question failed" in e.value for e in at.error)
    assert any(b.label == "Approve draft" for b in at.button)


def test_app_chat_history_stores_only_display_data(monkeypatch):
    at = app_ask(app_loaded(monkeypatch), "Read the condition at discharge")
    chat = at.session_state["chat"]
    assert chat
    for entry in chat:
        assert isinstance(entry, (tuple, dict))
        values = list(entry.values()) if isinstance(entry, dict) else list(entry)
        values += [v for x in values if isinstance(x, dict) for v in x.values()]
        assert not any(isinstance(v, Draft) for v in values)


def test_app_no_duplicate_ask_heading(monkeypatch):
    at = app_loaded(monkeypatch)
    assert not any(m.value == "### Ask about the notes" for m in at.markdown)
    assert any(t.label == "Ask about the notes" for t in at.text_input)


def test_conflict_prompt_flags_discrepancy(case, stub):
    draft, spans, events = case
    rg.ask(RATIONALE_Q, draft, spans, events)
    assert len(stub) == 1
    assert "Flagged for review" in user_msg(stub[0])
    assert draft.discrepancies[0].description in user_msg(stub[0])
    assert "cite every such passage" in system_msg(stub[0])


def test_non_conflict_prompt_has_no_flag(case, stub):
    draft, spans, events = case
    rg.ask(OXYGEN_Q, draft, spans, events)
    assert len(stub) == 1 and "Flagged for review" not in user_msg(stub[0])


def test_off_topic_question_skips_llm(case, stub):
    draft, spans, events = case
    out = rg.ask("What is the weather on Mars today?", draft, spans, events)
    assert out["answer"] == rg.NOT_ESTABLISHED and out["cited"] == [] and stub == []


def test_oxygen_question_still_retrieves(case, stub):
    draft, spans, events = case
    assert "note_04_p01_b09" in rg.ask(OXYGEN_Q, draft, spans, events)["retrieved"]


def test_rationale_replay_cites_conflict(case, monkeypatch):  # RED until re-recorded
    draft, spans, events = case
    monkeypatch.setattr(llm, "_call", lambda *a, **k: pytest.fail("no replay recording for the rationale question"))
    out = rg.ask(RATIONALE_Q, draft, spans, events)
    assert set(CONFLICT) <= set(out["cited"])


@pytest.mark.parametrize("question", ["Why do the notes mention different doses?", RATIONALE_Q])
def test_conflict_answers_attribute_flag_to_app_and_hide_ids(case, monkeypatch, question):  # review M1 + opt 1
    draft, spans, events = case
    monkeypatch.setattr(llm, "_call", lambda *a, **k: pytest.fail("no replay recording"))
    out = rg.ask(question, draft, spans, events)
    assert set(CONFLICT) <= set(out["cited"])
    assert "notes flag" not in out["answer"].lower()
    assert "note_0" not in out["answer"]


def test_passages_carry_note_dates(case, stub):  # review opt 2
    draft, spans, events = case
    rg.ask(RATIONALE_Q, draft, spans, events)
    assert "(note dated 2026-03-04 (Hospital Day 3))" in user_msg(stub[0])
