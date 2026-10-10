"""The only module that talks to OpenAI."""
import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

import anyio
import jiter
from dotenv import find_dotenv, load_dotenv
from openai import APIConnectionError, AsyncOpenAI, InternalServerError, OpenAI, RateLimitError
from pydantic import BaseModel

load_dotenv(find_dotenv(usecwd=True))  # does not override variables already set
TRANSIENT = (APIConnectionError, RateLimitError, InternalServerError)  # errors a retry can fix; includes timeouts


def _model() -> str:
    return os.environ.get("LLM_MODEL") or "gpt-6-luna"


def _call(schema: type[BaseModel], messages: list[dict], timeout: float) -> BaseModel:
    # max_retries=0: callers own retries (validation retry loop, graph RetryPolicy)
    parsed = OpenAI(timeout=timeout, max_retries=0).responses.parse(model=_model(), input=messages, text_format=schema, store=True).output_parsed
    if parsed is None:
        raise RuntimeError("model returned no parsed output")
    return parsed


def parse(schema: type[BaseModel], messages: list[dict], timeout: float) -> BaseModel:
    return _call(schema, messages, timeout)


async def stream_answer(schema: type[BaseModel], messages: list[dict], timeout: float) -> AsyncIterator[str | BaseModel]:
    """Yield decoded answer-field increments, then the validated structured result."""
    stack = AsyncExitStack()
    sent = ""
    try:
        client = await stack.enter_async_context(AsyncOpenAI(timeout=timeout, max_retries=0))
        stream = await stack.enter_async_context(client.responses.stream(
            model=_model(), input=messages, text_format=schema, store=True))
        async for event in stream:
            if event.type == "response.output_text.delta":
                # SDK 3.27.0 supplies the accumulated JSON snapshot, not partial parsed fields.
                if not event.snapshot.strip():
                    continue
                partial = jiter.from_json(event.snapshot.encode(), partial_mode="trailing-strings")
                text = partial.get("answer", "") if isinstance(partial, dict) else ""
                if not isinstance(text, str) or not text.startswith(sent):
                    raise RuntimeError("model returned inconsistent answer text")
                if text != sent:
                    delta, sent = text[len(sent):], text
                    yield delta
            elif event.type in ("error", "response.failed", "response.incomplete"):
                raise RuntimeError(f"model stream failed: {event.type}")
        out = (await stream.get_final_response()).output_parsed
        if out is None:
            raise RuntimeError("model returned no parsed output")
        if out.answer != sent:
            raise RuntimeError("model returned inconsistent final answer")
        yield out
    finally:
        # Starlette cancels the response task on disconnect; cleanup must survive that cancellation.
        with anyio.CancelScope(shield=True):
            await stack.aclose()
