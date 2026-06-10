"""Shared system-prompt directives injected into every new conversation."""

from __future__ import annotations

from local_agent.agent.skill_allowlist import SESSION_SKILL_ALLOWLIST_DIRECTIVE

LANGUAGE_DIRECTIVE = """\
交互与推理语言：
- 用户使用中文时，面向用户的回复必须使用中文。
- 流式推理（thinking / 思考过程）也必须用中文书写，便于用户在终端阅读；不要在思考中使用大段英文。"""

TOOLBOX_DIRECTIVE = """\
工具选用（每轮必遵）：
- 收到用户请求后，先阅读当轮注入的「工具箱」清单，从中选用与任务最匹配的工具再行动。
- 工具箱内各工具地位相同、均可直接调用；不要习惯性优先选用通用检索类工具，而忽略更贴合任务的领域专用工具。
- 任务涉及特定领域（如数据查询、文件操作、外部 API 等）时，优先选用该领域对应的专用工具，而非泛用替代方案。
- 仅当需要某技能或工具的完整操作说明时，再通过工具箱中提供的文档加载机制查阅，不要凭记忆臆测用法。"""


def default_system_directives() -> list[str]:
    """Agent-wide directives only. Per-skill rules live in SKILL.md and toolbox."""
    return [LANGUAGE_DIRECTIVE, TOOLBOX_DIRECTIVE, SESSION_SKILL_ALLOWLIST_DIRECTIVE]
