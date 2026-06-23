"""Pluggable LLM backends for the judgment nodes, with cross-call memory.

Two real backends:

- :class:`AnthropicBackend` — the Anthropic API via ``langchain-anthropic``.
  Memory is a running message history kept on the instance.
- :class:`ClaudeCodeBackend` — the local ``claude`` CLI in headless mode
  (``claude -p ... --output-format json``). Memory is carried by Claude Code's
  own session: the first call seeds the system prompt + records the returned
  ``session_id``; subsequent calls ``--resume`` that session so the model sees
  the whole prior conversation. This is the "headless with memory between LLM
  calls" path.

One backend instance is created per engine run and shared across the
fix/generate/integrate nodes, so state accumulates across the whole run.

:class:`FakeBackend` is used by tests to exercise apply-mode without spending
tokens.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Callable, Optional

from .config import Config, ModelConfig


class LLMBackend(ABC):
    name: str = "abstract"

    @abstractmethod
    def invoke(self, prompt: str, *, system: Optional[str] = None) -> str:
        """Send a prompt; the backend retains conversational memory itself."""

    # diagnostics
    calls: int = 0


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(self, mc: ModelConfig) -> None:
        from langchain_anthropic import ChatAnthropic

        self._chat = ChatAnthropic(
            model=mc.model, temperature=mc.temperature, max_tokens=mc.max_tokens
        )
        self._history: list[tuple[str, str]] = []
        self._system_sent = False
        self.calls = 0

    def invoke(self, prompt: str, *, system: Optional[str] = None) -> str:
        msgs: list[tuple[str, str]] = []
        if system and not self._system_sent:
            msgs.append(("system", system))
            self._system_sent = True
        msgs.extend(self._history)
        msgs.append(("human", prompt))
        resp = self._chat.invoke(msgs)
        content = resp.content
        if isinstance(content, list):
            text = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        else:
            text = str(content)
        self._history.append(("human", prompt))
        self._history.append(("ai", text))
        self.calls += 1
        return text


class ClaudeCodeBackend(LLMBackend):
    name = "claude-code"

    def __init__(self, mc: ModelConfig, *, timeout: float = 600.0) -> None:
        self._model = mc.claude_code_model  # None => use CLI default
        self._timeout = timeout
        self._session_id: Optional[str] = None
        self._bin = shutil.which("claude") or "claude"
        self.calls = 0

    def invoke(self, prompt: str, *, system: Optional[str] = None) -> str:
        prompt = prompt.replace("\x00", "")  # NUL bytes are illegal in argv
        cmd = [self._bin, "-p", prompt, "--output-format", "json"]
        if self._model:
            cmd += ["--model", self._model]
        if self._session_id:
            cmd += ["--resume", self._session_id]
        elif system:
            cmd += ["--append-system-prompt", system.replace("\x00", "")]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"claude headless failed rc={proc.returncode}: "
                               f"{proc.stderr[:300]}")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"claude headless: non-JSON output ({exc}): "
                               f"{proc.stdout[:200]}") from exc
        if data.get("is_error"):
            raise RuntimeError(f"claude headless error: {data.get('result')}")
        # chain memory: remember the session so the next call resumes it
        self._session_id = data.get("session_id") or self._session_id
        return data.get("result", "")


class FakeBackend(LLMBackend):
    """Deterministic backend for tests. ``responder(prompt) -> str``."""

    name = "fake"

    def __init__(self, responder: Callable[[str], str]) -> None:
        self._responder = responder
        self.prompts: list[str] = []
        self.calls = 0

    def invoke(self, prompt: str, *, system: Optional[str] = None) -> str:
        self.prompts.append(prompt)
        self.calls += 1
        return self._responder(prompt)


def backend_available(config: Config) -> bool:
    provider = config.model.provider
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if provider == "claude-code":
        return shutil.which("claude") is not None
    if provider == "fake":
        return True
    return False


def get_backend(config: Config) -> Optional[LLMBackend]:
    """Build a fresh, memory-carrying backend for one engine run (or None)."""
    if not backend_available(config):
        return None
    provider = config.model.provider
    if provider == "anthropic":
        return AnthropicBackend(config.model)
    if provider == "claude-code":
        return ClaudeCodeBackend(config.model)
    return None


__all__ = [
    "LLMBackend",
    "AnthropicBackend",
    "ClaudeCodeBackend",
    "FakeBackend",
    "get_backend",
    "backend_available",
]
