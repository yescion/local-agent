"""Normalize chat messages before sending them to LLM providers."""

from __future__ import annotations

import copy
from typing import Any

# Providers that require reasoning_content replay on historical tool-call turns.
_REASONING_REPLAY_MODEL_MARKERS = (
    "deepseek",
    "kimi-k2",  # Moonshot thinking + tool calls
    "kimi_k2",
)
_REASONING_REPLAY_BASE_MARKERS = (
    "deepseek",
    "opencode.ai",
    "moonshot",
)


def needs_reasoning_replay(model: str | None = None, api_base: str | None = None) -> bool:
    """Whether outgoing history must map `thinking` -> `reasoning_content`."""
    model_key = (model or "").lower()
    if any(marker in model_key for marker in _REASONING_REPLAY_MODEL_MARKERS):
        return True
    base_key = (api_base or "").lower()
    return any(marker in base_key for marker in _REASONING_REPLAY_BASE_MARKERS)


def _reasoning_text(message: dict[str, Any]) -> str:
    for key in ("reasoning_content", "thinking"):
        value = message.get(key)
        if isinstance(value, str):
            return value
    return ""


def prepare_messages_for_api(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    api_base: str | None = None,
) -> list[dict[str, Any]]:
    """
    Adapt persisted messages for the active provider.

    - `thinking` is our internal persistence/display field and is never sent as-is.
    - DeepSeek-style thinking mode needs `reasoning_content` on historical tool-call
      assistant turns; other OpenAI-compatible endpoints should not receive it.
    """
    replay_reasoning = needs_reasoning_replay(model, api_base)
    prepared: list[dict[str, Any]] = []
    for message in messages:
        msg = copy.deepcopy(message)
        if msg.get("role") == "assistant" and msg.get("tool_calls") and replay_reasoning:
            msg["reasoning_content"] = _reasoning_text(msg)
        msg.pop("thinking", None)
        prepared.append(msg)
    return prepared
