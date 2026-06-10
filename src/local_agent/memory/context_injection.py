"""Lightweight per-turn memory context injection helpers."""

from __future__ import annotations

from local_agent.config.models import RetrievalConfig

MEMORY_CONTEXT_PREFIX = "## 相关长期记忆"

_SKIP_PHRASES = frozenset(
    {
        "好",
        "好的",
        "ok",
        "okay",
        "yes",
        "继续",
        "嗯",
        "行",
        "可以",
        "谢谢",
        "thanks",
        "thank you",
    }
)


def is_memory_context_system_message(content: str) -> bool:
    return content.startswith(MEMORY_CONTEXT_PREFIX)


def should_auto_inject_memory(query: str, config: RetrievalConfig) -> bool:
    q = (query or "").strip()
    if len(q) < config.auto_inject_min_query_chars:
        return False
    if q in _SKIP_PHRASES:
        return False
    if q == "（用户仅发送了附件）":
        return False
    return True


def format_memory_context_block(results: list[str]) -> str:
    if not results:
        return ""
    lines = [MEMORY_CONTEXT_PREFIX, "以下是与本轮用户输入相关的长期记忆，供回答时参考："]
    lines.extend(f"- {item}" for item in results)
    return "\n".join(lines)
