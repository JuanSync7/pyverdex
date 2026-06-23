"""LLM client factory for the judgment nodes.

The deterministic nodes (lint/audit/measurement) never touch this. Only the
authoring/judgment nodes — fix, generate, evaluate-rationale, integrate —
call an LLM, always with a system prompt distilled from the vendored skill
docs (see :mod:`pyverify.knowledge`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional, TypeVar

from pydantic import BaseModel

from .config import Config, ModelConfig

T = TypeVar("T", bound=BaseModel)


def llm_available() -> bool:
    """True when an Anthropic API key is present in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@lru_cache(maxsize=4)
def _build(provider: str, model: str, temperature: float, max_tokens: int):
    if provider != "anthropic":
        raise ValueError(f"unsupported LLM provider: {provider!r}")
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_chat(mc: ModelConfig):
    return _build(mc.provider, mc.model, mc.temperature, mc.max_tokens)


def complete(config: Config, system: str, user: str) -> str:
    """Plain text completion."""
    chat = get_chat(config.model)
    resp = chat.invoke([("system", system), ("human", user)])
    content = resp.content
    if isinstance(content, list):  # content blocks
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content)


def complete_structured(
    config: Config, system: str, user: str, schema: type[T]
) -> Optional[T]:
    """Structured completion validated against a pydantic schema."""
    chat = get_chat(config.model).with_structured_output(schema)
    result = chat.invoke([("system", system), ("human", user)])
    if isinstance(result, schema):
        return result
    if isinstance(result, dict):
        return schema.model_validate(result)
    return None


__all__ = ["llm_available", "get_chat", "complete", "complete_structured"]
