"""Tool schema helpers."""

from __future__ import annotations

import re
from typing import Any, Callable

_API_TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def to_api_tool_name(name: str) -> str:
    """Normalize internal tool names for OpenAI-compatible providers (e.g. DeepSeek)."""
    api_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    if not api_name or not _API_TOOL_NAME_RE.match(api_name):
        raise ValueError(f"Invalid tool name after sanitization: {name!r} -> {api_name!r}")
    return api_name


def make_tool_schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


ToolHandler = Callable[..., str]
