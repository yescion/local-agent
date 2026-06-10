"""Unified toolbox catalog — all tools listed equally, no builtin vs skill split."""

from __future__ import annotations

from typing import TYPE_CHECKING

from local_agent.skills.catalog import (
    SANDBOX_RELEASE_HINT,
    SKILL_STUDIO_TOOLS_HINT,
    extract_catalog_sections,
    is_sandbox_related_skill,
)


if TYPE_CHECKING:
    from local_agent.skills.registry import SkillRegistry


def build_toolbox_catalog(
    registry: SkillRegistry,
    skill_ids: list[str] | None = None,
) -> str:
    """Build toolbox inventory for agent context and manage_skills(catalog).

    When skill_ids is set, only those skills are listed (session/agent allowlist).
    """
    skills = registry.list_skills()
    if skill_ids is not None:
        allowed = set(skill_ids)
        skills = [s for s in skills if s.id in allowed]
    lines = [
        "## 工具箱",
        "",
    ]
    if skill_ids is not None:
        lines.append(
            "下列为当前会话技能白名单内的工具（未列出的技能不可调用，"
            "即使其他文档中提及也不可 load 或变通实现）。"
        )
    else:
        lines.append(
            "处理用户请求前，先对照本清单选用最匹配的工具。下列工具均可直接调用。"
        )
    lines.append("")

    general: list[tuple[str, str]] = []
    for internal_name, schema in registry.tool_router._schemas.items():
        if internal_name.startswith("skill."):
            continue
        fn = schema.get("function") or {}
        api_name = str(fn.get("name") or internal_name)
        desc = str(fn.get("description") or "").strip()
        general.append((api_name, desc))

    if general:
        lines.append("### 通用工具")
        for name, desc in sorted(general, key=lambda x: x[0]):
            lines.append(f"- `{name}`: {desc}" if desc else f"- `{name}`")
        lines.append("")

    if not skills:
        lines.append("(暂无技能包)")
        return "\n".join(lines)

    for meta in skills:
        lines.append(f"### {meta.id} · {meta.name}")
        if meta.description:
            lines.append(meta.description)
        notes = extract_catalog_sections(meta.content)
        if notes:
            lines.append(notes)
        if meta.id == "skill_studio":
            lines.append(SKILL_STUDIO_TOOLS_HINT)
        if is_sandbox_related_skill(skill_id=meta.id, execution=meta.execution):
            if meta.execution == "sandbox":
                lines.append("执行环境: Daytona 沙盒（临时）")
            if "## 沙盒释放（必须）" not in (notes or ""):
                lines.append(SANDBOX_RELEASE_HINT)
        if meta.tools:
            for tool_name in meta.tools:
                desc = registry.tool_description(meta.id, tool_name)
                lines.append(f"- `{tool_name}`: {desc}" if desc else f"- `{tool_name}`")
        else:
            lines.append("(指引型技能，无独立工具)")
        lines.append("")

    lines.append(
        "说明：需要某技能的完整操作文档时，可调用 "
        'manage_skills(action="load", name="技能id")。'
    )
    return "\n".join(lines).rstrip()
