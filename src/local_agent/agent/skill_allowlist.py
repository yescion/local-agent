"""Session / agent skill allowlist helpers for prompts and tool errors."""

from __future__ import annotations


SESSION_SKILL_ALLOWLIST_DIRECTIVE = """\
会话技能白名单（强制）：
- 每个对话可在 Web UI「会话配置 → 允许使用的技能」或 Agent 创建时限定技能子集。
- 每轮注入的「工具箱」与 LLM 可见的工具函数均已按白名单过滤；未授权技能的工具不会出现在工具列表中。
- 若工具返回「未在本会话允许列表中」，这是刻意的访问控制，不是临时故障或权限 bug：
  1. 立即停止用其他工具、脚本或变通方式实现同一能力；
  2. 不要 manage_skills(load) 加载未授权技能（同样会被拒绝）；
  3. 向用户说明：需在「会话配置 → 允许使用的技能」中勾选对应技能，或由管理员调整 Agent 默认技能集后重试。
- 任务超出当前白名单时，如实告知限制原因，不要自行绕过。"""


def format_skill_blocked_error(
    skill_id: str,
    *,
    tool_name: str | None = None,
    action: str = "调用",
) -> str:
    """User- and agent-facing message when a skill is outside the allowlist."""
    if tool_name:
        action_part = f"{action}工具 {tool_name}"
    else:
        action_part = f"{action}技能"
    return (
        f"错误：技能「{skill_id}」未在本会话允许列表中，无法{action_part}。\n"
        "这是用户在「会话配置」或 Agent 默认设置中配置的技能白名单限制，"
        "属于刻意的访问控制，不可绕过。\n"
        "处理方式：向用户说明需要在 Web UI「会话配置 → 允许使用的技能」中勾选该技能"
        "（或由管理员调整 Agent 技能集）后重试。"
        "不要用其他工具、脚本或变通方式替代实现同一能力，也不要 manage_skills(load) 未授权技能。"
    )


def build_allowlist_notice(skill_ids: list[str], *, source: str) -> str:
    """Per-turn reminder when the conversation has a skill allowlist."""
    ids = "、".join(skill_ids) if skill_ids else "（无）"
    return (
        f"## 技能白名单（{source}）\n"
        f"本对话仅允许使用以下技能：{ids}\n"
        "每轮「工具箱」与可调用的工具函数均已按此过滤。"
        "若工具返回「未在本会话允许列表中」，请停止绕过尝试，并告知用户在会话配置中启用对应技能。"
    )
