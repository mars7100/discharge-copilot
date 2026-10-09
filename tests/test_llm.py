import json

import pytest
from pydantic import BaseModel

from core import llm


class Out(BaseModel):
    answer: str


MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_RECORD_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-SENTINEL-123")
    monkeypatch.setattr(llm, "_call", lambda schema, messages: pytest.fail("live call attempted"))


def test_request_key_deterministic_and_message_sensitive():
    k = llm.request_key(Out, MSGS)
    assert k == llm.request_key(Out, [dict(m) for m in MSGS])
    assert k != llm.request_key(Out, [{"role": "user", "content": "bye"}])
    assert len(k) == 64 and int(k, 16) >= 0


def test_replay_reads_file_without_calling(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "replay")
    (tmp_path / f"{llm.request_key(Out, MSGS)}.json").write_text(Out(answer="recorded").model_dump_json())
    assert llm.parse(Out, MSGS) == Out(answer="recorded")


def test_replay_missing_file_explains(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "replay")
    with pytest.raises(FileNotFoundError) as e:
        llm.parse(Out, MSGS)
    assert llm.request_key(Out, MSGS) in str(e.value) and "LLM_MODE=record" in str(e.value)


def test_record_writes_output_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "record")
    monkeypatch.setattr(llm, "_call", lambda schema, messages: Out(answer="fresh"))
    assert llm.parse(Out, MSGS) == Out(answer="fresh")
    text = (tmp_path / f"{llm.request_key(Out, MSGS)}.json").read_text()
    assert json.loads(text) == {"answer": "fresh"}
    assert "sk-SENTINEL-123" not in text


def test_live_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODE", raising=False)  # default is live
    monkeypatch.setattr(llm, "_call", lambda schema, messages: Out(answer="live"))
    assert llm.parse(Out, MSGS) == Out(answer="live")
    assert list(tmp_path.iterdir()) == []


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
    explicit = llm.request_key(Out, MSGS)
    monkeypatch.delenv("LLM_MODEL")
    assert llm.request_key(Out, MSGS) == explicit
    seen = fake_openai(monkeypatch, Out(answer="ok"))
    REAL_CALL(Out, MSGS)
    assert seen["model"] == "gpt-6-luna"


def test_call_uses_responses_api_without_storage(monkeypatch):
    seen = fake_openai(monkeypatch, Out(answer="parsed"))
    assert REAL_CALL(Out, MSGS) == Out(answer="parsed")
    assert seen == {"model": "test-model", "input": MSGS, "text_format": Out, "store": False}


def test_call_raises_when_no_parsed_output(monkeypatch):
    fake_openai(monkeypatch, None)
    with pytest.raises(Exception, match="no parsed output"):
        REAL_CALL(Out, MSGS)


def test_call_sets_client_timeout(monkeypatch):
    init = {}
    seen = fake_openai(monkeypatch, Out(answer="ok"))
    Base = llm.OpenAI

    class Recording(Base):
        def __init__(self, *a, **k):
            init.update(k)
            super().__init__(*a, **k)

    monkeypatch.setattr(llm, "OpenAI", Recording)
    REAL_CALL(Out, MSGS)
    assert init.get("timeout") == 120
    assert seen == {"model": "test-model", "input": MSGS, "text_format": Out, "store": False}
