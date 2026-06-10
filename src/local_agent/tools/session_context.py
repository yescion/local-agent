"""Per-turn agent/thread session context for tools and prompts."""

from __future__ import annotations

import json
import re
from contextvars import ContextVar

_agent_id: ContextVar[str | None] = ContextVar("session_agent_id", default=None)
_thread_id: ContextVar[str | None] = ContextVar("session_thread_id", default=None)
_agent_name: ContextVar[str | None] = ContextVar("session_agent_name", default=None)

_ARTIFACT_SESSION_RE = re.compile(
    r"artifacts[/\\]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"[/\\]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


def set_turn_session_context(
    agent_id: str,
    thread_id: str,
    *,
    agent_name: str = "",
) -> None:
    _agent_id.set(agent_id)
    _thread_id.set(thread_id)
    _agent_name.set(agent_name or None)


def clear_turn_session_context() -> None:
    _agent_id.set(None)
    _thread_id.set(None)
    _agent_name.set(None)


def get_turn_session_context() -> tuple[str | None, str | None]:
    return _agent_id.get(), _thread_id.get()


def format_session_context_lines(agent_id: str, thread_id: str) -> str:
    return (
        f"当前会话 agent_id: {agent_id}\n"
        f"当前会话 thread_id: {thread_id}"
    )


def format_session_context_block() -> str:
    agent_id, thread_id = get_turn_session_context()
    if not agent_id or not thread_id:
        return ""
    lines = ["## 当前会话", format_session_context_lines(agent_id, thread_id)]
    name = _agent_name.get()
    if name:
        lines.append(f"agent_name: {name}")
    lines.append(
        "创建宿主机定时任务（job_create）时须绑定上述 agent_id 与 thread_id，"
        "任务才会出现在 Web UI 的会话任务列表中；未传时会自动使用当前会话。"
    )
    return "\n".join(lines)


def get_session_context_json() -> str:
    agent_id, thread_id = get_turn_session_context()
    if not agent_id or not thread_id:
        return json.dumps({"error": "无活动会话上下文"}, ensure_ascii=False)
    payload: dict[str, str] = {"agent_id": agent_id, "thread_id": thread_id}
    name = _agent_name.get()
    if name:
        payload["agent_name"] = name
    return json.dumps(payload, ensure_ascii=False)


def infer_session_from_artifact_path(path: str) -> tuple[str | None, str | None]:
    match = _ARTIFACT_SESSION_RE.search(path or "")
    if not match:
        return None, None
    return match.group(1), match.group(2)


def resolve_session_ids(
    *,
    agent_id: str | None = None,
    thread_id: str | None = None,
    artifact_path: str | None = None,
) -> tuple[str | None, str | None]:
    """Fill missing session IDs from turn context, then artifact path."""
    aid = (agent_id or "").strip() or None
    tid = (thread_id or "").strip() or None
    if not aid or not tid:
        ctx_aid, ctx_tid = get_turn_session_context()
        aid = aid or ctx_aid
        tid = tid or ctx_tid
    if (not aid or not tid) and artifact_path:
        inf_aid, inf_tid = infer_session_from_artifact_path(artifact_path)
        aid = aid or inf_aid
        tid = tid or inf_tid
    return aid, tid
