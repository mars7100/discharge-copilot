"""The only module that talks to OpenAI. LLM_MODE: live (default) | record | replay (spec §7.2)."""
import hashlib
import json
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv(find_dotenv(usecwd=True))  # does not override variables already set


def _model() -> str:
    return os.environ.get("LLM_MODEL") or "gpt-6-luna"


def request_key(schema: type[BaseModel], messages: list[dict]) -> str:
    payload = {"model": _model(), "messages": messages, "schema": schema.model_json_schema()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _call(schema: type[BaseModel], messages: list[dict]) -> BaseModel:
    parsed = OpenAI(timeout=30).responses.parse(model=_model(), input=messages, text_format=schema, store=False).output_parsed
    if parsed is None:
        raise RuntimeError("model returned no parsed output")
    return parsed


def parse(schema: type[BaseModel], messages: list[dict], mode: str | None = None) -> BaseModel:
    mode = mode or os.environ.get("LLM_MODE", "live")
    path = Path(os.environ.get("LLM_RECORD_DIR", "fixtures/recorded")) / f"{request_key(schema, messages)}.json"
    if mode == "replay":
        if not path.exists():
            raise FileNotFoundError(f"no recording {path.name} (key {path.stem}); re-run with LLM_MODE=record")
        return schema.model_validate_json(path.read_text())
    result = _call(schema, messages)
    if mode == "record":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=2))
    return result
