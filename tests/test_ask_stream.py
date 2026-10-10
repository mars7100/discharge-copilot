"""Stream contract, real SDK event shapes, history interoperability, and cancellation."""
import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from openai.lib.streaming.responses import ResponseTextDeltaEvent

import api.app as routes
from api import sessions
from api.schemas import Ask
from core import llm, review_graph as rg
from core.models import Draft, SourceSpan, SummaryClaim


@pytest.fixture
def ready() -> str:
    """Create a reviewable case without invoking a model."""
    sid = sessions.create("case_001")
    spans = {"note_01_p01_b02": SourceSpan(
        span_id="note_01_p01_b02", document_id="note_01", filename="note_01.txt", page=1,
        order=2, text="Admitted with pneumonia.")}
    draft = Draft(claims=[SummaryClaim(claim_id="C01", section="reason_for_admission",
                                     text="Admitted.", evidence_span_ids=list(spans), support_status="supported")])
    sessions.update(sid, draft=draft, spans=spans)
    return sid


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Mock SDK I/O while using the installed SDK's typed text-delta events."""
    rec = SimpleNamespace(calls=[], closed=0, clients_closed=0, final=0, fail=False, block=False,
                          reached=None, release=None)

    class Stream:
        async def __aenter__(self) -> "Stream":
            """Enter the SDK stream manager."""
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Record stream closure."""
            rec.closed += 1

        async def __aiter__(self) -> AsyncIterator[ResponseTextDeltaEvent]:
            """Yield genuine structured-output snapshots in multiple network increments."""
            snapshot = ""
            for index, delta in enumerate([' ', '{"answer":"Admitted', ' with pneumonia.\\n',
                                            'Quote: \\"yes\\"", "span_ids":["note_01_p01_b02","bogus"]}']):
                snapshot += delta
                yield ResponseTextDeltaEvent(type="response.output_text.delta", delta=delta, snapshot=snapshot,
                                            content_index=0, output_index=0, item_id="msg_1",
                                            sequence_number=index, logprobs=[])
                if index == 1:
                    if rec.reached:
                        rec.reached.set()
                    if rec.block:
                        await rec.release.wait()
                    if rec.fail:
                        raise RuntimeError("boom")

        async def get_final_response(self) -> SimpleNamespace:
            """Return the SDK-validated final structured output."""
            rec.final += 1
            return SimpleNamespace(output_parsed=rg.Answer(
                answer='Admitted with pneumonia.\nQuote: "yes"', span_ids=["note_01_p01_b02", "bogus"]))

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            """Record SDK construction and expose its responses resource."""
            rec.init = kwargs
            self.responses = self

        async def __aenter__(self) -> "Client":
            """Enter the client context."""
            return self

        async def __aexit__(self, *args: Any) -> None:
            """Record client closure."""
            rec.clients_closed += 1

        def stream(self, **kwargs: Any) -> Stream:
            """Record the actual responses.stream call."""
            rec.calls.append(kwargs)
            return Stream()

    monkeypatch.setattr(llm, "AsyncOpenAI", Client)
    monkeypatch.setattr(llm, "parse", lambda *args: rg.Answer(answer="JSON answer", span_ids=["bogus"]))
    return rec


def decode(body: str) -> list[tuple[str, dict]]:
    """Decode complete SSE blocks."""
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((fields["event"], json.loads(fields["data"])))
    return out


def test_sse_contract_and_json_interoperability(ready: str, sdk: SimpleNamespace) -> None:
    """Filter citations and share the last three turns with the unchanged JSON endpoint."""
    client = TestClient(routes.app)
    url = f"/api/sessions/{ready}/ask"
    assert client.post(url, json={"question": "What happened?"}).json() == {
        "intent": "question", "answer": "JSON answer", "cited": []}
    for question in ["Read reason for admission", "What was given?", "And next?"]:
        response = client.post(url + "/stream", json={"question": question})
        assert response.status_code == 200
    events = decode(response.text)
    assert [name for name, _ in events] == ["status", "status", "status", "delta", "delta", "delta", "answer", "done"]
    assert [data["stage"] for name, data in events if name == "status"] == ["classifying", "retrieving", "answering"]
    final = events[-2][1]
    assert final == {"intent": "question", "answer": 'Admitted with pneumonia.\nQuote: "yes"',
                     "cited": ["note_01_p01_b02"]}
    assert "".join(data["text"] for name, data in events if name == "delta") == final["answer"]
    messages = sdk.calls[-1]["input"]
    assert [m["content"] for m in messages if m["role"] == "user"][:-1] == [
        "What happened?", "Read reason for admission", "What was given?"]
    assert "Earlier answers are not evidence" in messages[1]["content"]
    assert sdk.calls[-1]["text_format"] is rg.Answer and sdk.calls[-1]["store"] is True
    assert sdk.init == {"timeout": 35, "max_retries": 0}
    assert sdk.closed == sdk.clients_closed == 2
    s = sessions.get(ready)
    result = rg.ask("Then what?", s["draft"], s["spans"], thread_id=s["chat_thread_id"])
    assert [turn["q"] for turn in result["turns"]][-2:] == ["And next?", "Then what?"]


def test_incremental_before_completion(ready: str, sdk: SimpleNamespace) -> None:
    """The first answer increment arrives before the SDK final response is read."""
    async def run() -> None:
        """Drive only as far as the first text delta, then close."""
        s = sessions.get(ready)
        stream = rg.ask_stream("What happened?", s["draft"], s["spans"], thread_id=s["chat_thread_id"])
        while (event := await anext(stream))[0] != "delta":
            pass
        assert event == ("delta", {"text": "Admitted"})
        assert sdk.final == 0
        await stream.aclose()
        assert sdk.closed == sdk.clients_closed == 1
        assert not rg.graph.get_state({"configurable": {"thread_id": s["chat_thread_id"]}}).values
    asyncio.run(run())


def test_failure_has_error_no_done_or_partial_turn(ready: str, sdk: SimpleNamespace) -> None:
    """A failed stream releases resources and leaves conversation history untouched."""
    sdk.fail = True
    client = TestClient(routes.app)
    response = client.post(f"/api/sessions/{ready}/ask/stream", json={"question": "What happened?"})
    events = decode(response.text)
    assert events[-1] == ("error", {"detail": "RuntimeError: boom"})
    assert not any(name in ("answer", "done") for name, _ in events)
    assert sdk.closed == sdk.clients_closed == 1 and ready not in routes.ASK_RUNNING
    config = {"configurable": {"thread_id": sessions.get(ready)["chat_thread_id"]}}
    assert not rg.graph.get_state(config).values


def test_cancellation_closes_sdk_and_releases_overlap_guard(ready: str, sdk: SimpleNamespace) -> None:
    """Cancel a blocked model read, like Starlette does on an ASGI disconnect."""
    async def run() -> None:
        """Cancel the response iterator while the SDK is waiting for another increment."""
        sdk.block, sdk.reached, sdk.release = True, asyncio.Event(), asyncio.Event()

        class Request:
            async def is_disconnected(self) -> bool:
                """Keep consuming until cancellation."""
                return False

        response = await routes.stream_question(ready, Ask(question="What happened?"), Request())

        async def consume() -> None:
            """Consume streamed response events."""
            async for _ in response.body_iterator:
                pass

        task = asyncio.create_task(consume())
        await asyncio.wait_for(sdk.reached.wait(), 2)
        with pytest.raises(HTTPException, match="ask running"):
            await routes.stream_question(ready, Ask(question="And next?"), Request())
        with pytest.raises(HTTPException, match="ask running"):
            routes.ask_question(ready, Ask(question="And next?"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sdk.closed == sdk.clients_closed == 1 and ready not in routes.ASK_RUNNING
        assert not rg.graph.get_state({"configurable": {"thread_id": sessions.get(ready)["chat_thread_id"]}}).values
    asyncio.run(run())


def test_readiness_and_non_model_intents(ready: str, sdk: SimpleNamespace) -> None:
    """Preserve 404/409 readiness, blank validation, and deterministic intents."""
    client = TestClient(routes.app)
    url = f"/api/sessions/{ready}/ask/stream"
    assert client.post("/api/sessions/missing/ask/stream", json={"question": "What happened?"}).status_code == 404
    assert client.post(url, json={"question": " "}).status_code == 422
    sessions.update(ready, load_running=True)
    assert client.post(url, json={"question": "What happened?"}).json() == {"detail": "load running"}
    sessions.update(ready, load_running=False)
    assert decode(client.post(url, json={"question": "hi"}).text)[-2][1]["intent"] == "unknown"
    assert decode(client.post(url, json={"question": "Read reason for admission"}).text)[-2][1] == {
        "intent": "read_section", "answer": "Admitted.", "cited": ["note_01_p01_b02"]}
    sessions.update(ready, spans={})
    assert decode(client.post(url, json={"question": "What happened?"}).text)[-2][1] == {
        "intent": "question", "answer": rg.NOT_ESTABLISHED, "cited": []}
    assert sdk.calls == []
    sessions.update(ready, draft=None)
    response = client.post(url, json={"question": "What happened?"})
    assert response.status_code == 409 and response.json() == {"detail": "no draft"}


def test_asgi_disconnect_cancels_blocked_stream(ready: str, sdk: SimpleNamespace) -> None:
    """An actual Starlette disconnect cancels model I/O and shielded cleanup finishes."""
    async def run() -> None:
        """Drive ASGI response sending, then deliver http.disconnect after a partial answer."""
        sdk.block, sdk.reached, sdk.release = True, asyncio.Event(), asyncio.Event()
        sent = []

        class Request:
            async def is_disconnected(self) -> bool:
                """Leave ASGI disconnect listening to StreamingResponse."""
                return False

        async def receive() -> dict:
            """Disconnect once the model waits for its next increment."""
            await sdk.reached.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            """Capture response events actually sent before disconnect."""
            sent.append(message)

        response = await routes.stream_question(ready, Ask(question="What happened?"), Request())
        await asyncio.wait_for(response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send), 2)
        body = b"".join(message.get("body", b"") for message in sent).decode()
        assert 'event: delta\ndata: {"text": "Admitted"}' in body
        assert "event: answer" not in body and "event: done" not in body
        assert sdk.closed == sdk.clients_closed == 1 and ready not in routes.ASK_RUNNING
        assert not rg.graph.get_state({"configurable": {"thread_id": sessions.get(ready)["chat_thread_id"]}}).values

    asyncio.run(run())


@pytest.mark.parametrize("terminal", ["completed", "incomplete", "failed"])
def test_installed_sdk_wire_events(monkeypatch: pytest.MonkeyPatch, terminal: str) -> None:
    """Exercise installed SDK parsing and final response through a mocked HTTP transport."""
    response = {"id": "r1", "object": "response", "created_at": 0, "status": "in_progress",
                "model": "test", "output": []}
    message = {"type": "message", "id": "msg_1", "status": "in_progress", "role": "assistant",
               "phase": "final_answer", "content": []}
    deltas = ['{"answer":"Actual', ' SDK", "span_ids":[]}']
    text = "".join(deltas)
    events = [
        {"type": "response.created", "response": response},
        {"type": "response.output_item.added", "output_index": 0, "item": message},
        {"type": "response.content_part.added", "item_id": "msg_1", "output_index": 0, "content_index": 0,
         "part": {"type": "output_text", "text": "", "annotations": [], "logprobs": []}},
        *[{"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0,
           "content_index": 0, "delta": delta, "logprobs": []} for delta in deltas],
        {"type": f"response.{terminal}", "response": {**response, "status": terminal, "output": [
            {**message, "status": "completed", "content": [
                {"type": "output_text", "text": text, "annotations": [], "logprobs": []}]}]}},
    ]
    wire = "".join(f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': i})}\n\n"
                   for i, event in enumerate(events))
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        """Return raw provider SSE without contacting a network service."""
        requests.append(json.loads(request.content))
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=wire)

    def client(**kwargs: Any) -> AsyncOpenAI:
        """Construct the real installed client with a mocked transport and explicit test key."""
        return AsyncOpenAI(api_key="test-key", http_client=httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)), **kwargs)

    monkeypatch.setattr(llm, "AsyncOpenAI", client)

    async def run() -> None:
        """Read increments independently of the final structured response."""
        stream = llm.stream_answer(rg.Answer, [{"role": "user", "content": "What happened?"}], 35)
        assert await anext(stream) == "Actual"
        assert await anext(stream) == " SDK"
        if terminal == "completed":
            assert await anext(stream) == rg.Answer(answer="Actual SDK", span_ids=[])
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
        else:
            with pytest.raises(RuntimeError, match=f"response.{terminal}"):
                await anext(stream)
        await stream.aclose()

    asyncio.run(run())
    assert requests[0]["stream"] is True and requests[0]["store"] is True
    assert requests[0]["text"]["format"]["type"] == "json_schema"
