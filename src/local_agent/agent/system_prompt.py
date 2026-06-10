"""Helpers for patching persisted system prompts."""

from __future__ import annotations

L3_PERSONA_PREFIX = "L3 Persona:"
ACTIVE_SKILL_PREFIX = "Active Skill:"

_TURN_CONTEXT_PREFIXES = (
    "## 当前环境上下文",
    "## 当前会话",
    "技能工具箱：",
    "工具执行环境：",
)


def is_turn_context_system_message(content: str) -> bool:
    """Whether a system message was injected per user turn (not the base prompt)."""
    return any(content.startswith(prefix) for prefix in _TURN_CONTEXT_PREFIXES)


def _part_is_standalone_persona(part: str) -> bool:
    return part.startswith("你是")


def _strip_merged_session_persona(part: str) -> str:
    """Remove persona lines merged into a session-ID block (legacy prepend bug)."""
    if not part.startswith("当前会话 agent_id:"):
        return part
    marker = "\n你是"
    idx = part.find(marker)
    if idx == -1:
        return part
    return part[:idx].rstrip()


def patch_persona_in_system_content(content: str, persona_prompt: str) -> str:
    """Replace the persona block in a base system message, or prepend if missing."""
    parts = content.split("\n\n")
    replaced = False
    patched: list[str] = []
    for part in parts:
        if _part_is_standalone_persona(part):
            if not replaced:
                patched.append(persona_prompt)
                replaced = True
            continue
        stripped = _strip_merged_session_persona(part)
        if stripped:
            patched.append(stripped)
    if not replaced:
        patched.insert(0, persona_prompt)
    return "\n\n".join(patched)


def is_standalone_active_skill_message(msg: dict) -> bool:
    if msg.get("role") != "system":
        return False
    content = msg.get("content")
    return isinstance(content, str) and content.startswith(ACTIVE_SKILL_PREFIX)


def strip_active_skill_from_system_content(content: str) -> str:
    """Remove an embedded Active Skill block from a base system message."""
    parts = content.split("\n\n")
    kept = [part for part in parts if not part.startswith(ACTIVE_SKILL_PREFIX)]
    return "\n\n".join(kept)


def dedupe_active_skill_in_messages(messages: list[dict]) -> list[dict]:
    """Remove standalone and embedded Active Skill blocks before re-injecting one."""
    result: list[dict] = []
    for msg in messages:
        if is_standalone_active_skill_message(msg):
            continue
        content = msg.get("content")
        if (
            msg.get("role") == "system"
            and isinstance(content, str)
            and not is_turn_context_system_message(content)
            and not content.startswith("PREVIOUS SUMMARY:")
        ):
            cleaned = strip_active_skill_from_system_content(content)
            if cleaned != content:
                result.append({**msg, "content": cleaned})
                continue
        result.append(msg)
    return result


def patch_l3_persona_in_system_content(content: str, l3_persona: str) -> str:
    """Replace, append, or remove the L3 persona block in the base system message."""
    parts = content.split("\n\n")
    replaced = False
    patched: list[str] = []
    for part in parts:
        if part.startswith(L3_PERSONA_PREFIX):
            replaced = True
            if l3_persona.strip():
                patched.append(f"{L3_PERSONA_PREFIX}\n{l3_persona.strip()}")
        else:
            patched.append(part)
    if l3_persona.strip() and not replaced:
        patched.append(f"{L3_PERSONA_PREFIX}\n{l3_persona.strip()}")
    return "\n\n".join(patched)
