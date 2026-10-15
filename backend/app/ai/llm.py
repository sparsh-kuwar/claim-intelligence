"""Thin LLM clients (plain HTTP, no SDK). Keys come from env only."""
import json
import re

import httpx

from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.config import Settings


class LLMError(RuntimeError):
    pass


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("LLM response contained no JSON object")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned invalid JSON: {e}") from e


def call_anthropic(settings: Settings, **claim) -> dict:
    if not settings.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY not set")
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": settings.anthropic_model, "max_tokens": 1200, "temperature": 0,
              "system": SYSTEM_PROMPT,
              "messages": [{"role": "user", "content": build_user_prompt(**claim)}]},
        timeout=settings.llm_timeout_seconds,
    )
    if r.status_code != 200:
        raise LLMError(f"Anthropic API {r.status_code}")
    return _parse_json("".join(b.get("text", "") for b in r.json().get("content", [])))


def call_openai(settings: Settings, **claim) -> dict:
    if not settings.openai_api_key:
        raise LLMError("OPENAI_API_KEY not set")
    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json={"model": settings.openai_model, "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": build_user_prompt(**claim)}]},
        timeout=settings.llm_timeout_seconds,
    )
    if r.status_code != 200:
        raise LLMError(f"OpenAI API {r.status_code}")
    return _parse_json(r.json()["choices"][0]["message"]["content"])
