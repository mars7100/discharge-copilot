"""The only module that talks to OpenAI."""
import os

from dotenv import find_dotenv, load_dotenv
from openai import APIConnectionError, InternalServerError, OpenAI, RateLimitError
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
