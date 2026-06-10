"""Skill directory scanner and SKILL.md parser."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from local_agent.skills.models import SkillMetadata


def parse_skill_md(skill_path: Path) -> SkillMetadata:
    """Parse SKILL.md or standalone .md skill file."""
    post = frontmatter.load(skill_path)
    meta = post.metadata
    if meta.get("id"):
        skill_id = meta["id"]
    elif skill_path.name == "SKILL.md":
        skill_id = skill_path.parent.name
    else:
        skill_id = skill_path.stem
    execution = meta.get("execution", "host")
    if execution not in ("host", "sandbox"):
        execution = "host"
    return SkillMetadata(
        id=skill_id,
        name=meta.get("name", skill_id),
        version=meta.get("version", "1.0.0"),
        description=meta.get("description", ""),
        author=meta.get("author", ""),
        tags=meta.get("tags", []),
        tools=meta.get("tools", []),
        enabled=meta.get("enabled", True),
        execution=execution,
        path=skill_path,
        content=post.content.strip(),
    )


def discover_skills(
    directories: list[Path],
    exclude_dir_names: list[str] | None = None,
) -> list[Path]:
    """Find all SKILL.md files under skill directories (one skill per directory)."""
    excluded = set(exclude_dir_names or [])
    found: list[Path] = []
    seen: set[Path] = set()
    for directory in directories:
        if not directory.exists():
            continue
        for skill_md in directory.rglob("SKILL.md"):
            if excluded and any(part in excluded for part in skill_md.parts):
                continue
            resolved = skill_md.resolve()
            if resolved not in seen:
                seen.add(resolved)
                found.append(skill_md)
    return found
