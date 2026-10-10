import pytest
from pydantic import BaseModel

from core import llm


class Out(BaseModel):
    answer: str


MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-SENTINEL-123")
    monkeypatch.setattr(llm, "_call", lambda *a: pytest.fail("live call attempted"))


REAL_CALL = llm._call  # captured before the autouse fixture patches it


def fake_openai(monkeypatch, parsed):
    seen = {}

    class Responses:
        def parse(self, **kwargs):
            seen.update(kwargs)
            return type("Resp", (), {"output_parsed": parsed})()

    class FakeOpenAI:
        def __init__(self, *a, **k):
            self.responses = Responses()

        @property
        def chat(self):
            pytest.fail("chat.completions used")

    monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)
    return seen


def test_model_defaults_to_gpt_6_luna(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-6-luna")
    monkeypatch.delenv("LLM_MODEL")
    seen = fake_openai(monkeypatch, Out(answer="ok"))
    REAL_CALL(Out, MSGS, 35)
    assert seen["model"] == "gpt-6-luna"


def test_call_uses_responses_api_with_storage(monkeypatch):
    seen = fake_openai(monkeypatch, Out(answer="parsed"))
    assert REAL_CALL(Out, MSGS, 35) == Out(answer="parsed")
    assert seen == {"model": "test-model", "input": MSGS, "text_format": Out, "store": True}


def test_call_raises_when_no_parsed_output(monkeypatch):
    fake_openai(monkeypatch, None)
    with pytest.raises(Exception, match="no parsed output"):
        REAL_CALL(Out, MSGS, 35)


def test_call_sets_timeout_and_disables_client_retries(monkeypatch):
    init = {}
    seen = fake_openai(monkeypatch, Out(answer="ok"))
    Base = llm.OpenAI

    class Recording(Base):
        def __init__(self, *a, **k):
            init.update(k)
            super().__init__(*a, **k)

    monkeypatch.setattr(llm, "OpenAI", Recording)
    REAL_CALL(Out, MSGS, 35)
    assert init.get("timeout") == 35 and init.get("max_retries") == 0
    assert seen == {"model": "test-model", "input": MSGS, "text_format": Out, "store": True}
