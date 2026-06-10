"""Auto-generate short thread titles from conversation content."""

from __future__ import annotations

import re

from local_agent.llm.litellm_client import LiteLLMClient

MAX_TITLE_LEN = 24

_GENERIC_TITLES = frozenset({"", "新会话", "未命名会话"})


def is_generic_title(title: str | None) -> bool:
    """Return True when the title is empty or a placeholder that should be replaced."""
    if not title or not title.strip():
        return True
    normalized = title.strip()
    if normalized in _GENERIC_TITLES:
        return True
    return normalized.endswith("默认会话")


def clamp_title(title: str, max_len: int = MAX_TITLE_LEN) -> str:
    collapsed = " ".join(title.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[: max_len - 1] + "…"


def normalize_title(raw: str, max_len: int = MAX_TITLE_LEN) -> str:
    title = raw.strip().strip("\"'“”‘’`")
    for prefix in ("标题：", "标题:", "Title:", "title:"):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
    title = re.sub(r"[。．.!！?？…]+$", "", title.strip())
    return clamp_title(title, max_len)


def fallback_title_from_message(text: str, max_len: int = MAX_TITLE_LEN) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "新会话"
    return clamp_title(line, max_len)


async def generate_thread_title(
    llm: LiteLLMClient,
    user_message: str,
    assistant_message: str,
    *,
    max_len: int = MAX_TITLE_LEN,
) -> str:
    user_snippet = user_message.strip()[:500]
    assistant_snippet = assistant_message.strip()[:300]
    if not user_snippet:
        return fallback_title_from_message(assistant_snippet or "新会话", max_len)

    instruction = (
        f"根据以下对话生成一个简短的会话标题，不超过{max_len}个字。"
        "不要引号、不要标点结尾、不要解释，只输出标题文本。"
        f"\n\n用户：{user_snippet}"
    )
    if assistant_snippet:
        instruction += f"\n\n助手：{assistant_snippet}"

    try:
        resp = await llm.chat(
            [{"role": "user", "content": instruction}],
            temperature=0.3,
        )
        title = normalize_title(resp.content, max_len)
        if title:
            return title
    except Exception:
        pass
    return fallback_title_from_message(user_snippet, max_len)
