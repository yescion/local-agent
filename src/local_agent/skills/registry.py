"""Skill registry - register, unregister, load."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from sqlalchemy.orm import Session

from local_agent.skills.loader import discover_skills, parse_skill_md
from local_agent.skills.models import SkillMetadata
from local_agent.storage.models import SkillRow, utcnow
from local_agent.tools.router import ToolRouter
from local_agent.tools.schema import make_tool_schema
from local_agent.tools.toolbox import build_toolbox_catalog


class SkillRegistry:
    def __init__(
        self,
        directories: list[Path],
        tool_router: ToolRouter,
        session: Session | None = None,
        exclude_dir_names: list[str] | None = None,
    ) -> None:
        self.directories = directories
        self.exclude_dir_names = exclude_dir_names or []
        self.tool_router = tool_router
        self.session = session
        self._skills: dict[str, SkillMetadata] = {}

    def register(self, skill_path: Path) -> SkillMetadata:
        meta = parse_skill_md(skill_path)
        if meta.id in self._skills:
            self.unregister(meta.id)
        self._skills[meta.id] = meta
        tools_py = skill_path.parent / "tools.py"
        if tools_py.exists():
            if meta.execution == "sandbox":
                self._load_sandbox_skill_tools(meta, tools_py)
            else:
                self._load_skill_tools(meta, tools_py)
        if self.session:
            self._persist_skill(meta)
        return meta

    def unregister(self, skill_id: str) -> None:
        meta = self._skills.pop(skill_id, None)
        prefix = f"skill.{skill_id}."
        for tool_name in list(self.tool_router.list_tool_names()):
            if tool_name.startswith(prefix):
                self.tool_router.unregister(tool_name)
        if meta:
            self._unload_skill_tools_module(meta.id)
        if self.session:
            row = self.session.get(SkillRow, skill_id)
            if row:
                row.enabled = False
                self.session.commit()

    def reload(self, skill_id: str) -> SkillMetadata:
        meta = self._skills.get(skill_id)
        if not meta:
            raise KeyError(f"Skill not found: {skill_id}")
        return self.register(meta.path)

    def list_skills(self, enabled_only: bool = True) -> list[SkillMetadata]:
        skills = list(self._skills.values())
        if enabled_only:
            skills = [s for s in skills if s.enabled]
        return sorted(skills, key=lambda s: s.id)

    def get_skill(self, skill_id: str) -> SkillMetadata | None:
        return self._skills.get(skill_id)

    def load_skill(self, name: str) -> str:
        skill_id = name.removesuffix(".md")
        meta = self._skills.get(skill_id)
        if not meta:
            for s in self._skills.values():
                if s.path.name == name or s.path.stem == skill_id:
                    meta = s
                    break
        if not meta:
            return f"错误：未找到技能 — {name}"
        return meta.content

    def scan_directories(self) -> int:
        return self.rescan()

    def rescan(self) -> int:
        """Scan skill directories, register updates, and remove stale skills."""
        found_paths = discover_skills(
            self.directories, exclude_dir_names=self.exclude_dir_names
        )
        found_ids: set[str] = set()
        for path in found_paths:
            meta = self.register(path)
            found_ids.add(meta.id)
        for skill_id in list(self._skills):
            if skill_id not in found_ids:
                self.unregister(skill_id)
        return len(found_ids)

    def get_skill_summaries(self) -> str:
        lines = [s.summary_line() for s in self.list_skills()]
        return "\n".join(lines) if lines else "(无可用技能)"

    def get_toolbox_catalog(self, skill_ids: list[str] | None = None) -> str:
        """Unified toolbox inventory (general + skill tools, no load gate)."""
        return build_toolbox_catalog(self, skill_ids=skill_ids)

    def get_skill_catalog(self, skill_ids: list[str] | None = None) -> str:
        """Alias for manage_skills(catalog), filtered by allowed skill IDs."""
        return self.get_toolbox_catalog(skill_ids=skill_ids)

    def tool_description(self, skill_id: str, tool_name: str) -> str:
        internal = f"skill.{skill_id}.{tool_name}"
        schema = self.tool_router._schemas.get(internal)
        if not schema:
            return ""
        fn = schema.get("function") or {}
        return str(fn.get("description") or "")

    def _unload_skill_tools_module(self, skill_id: str) -> None:
        module_name = f"skill_tools_{skill_id}"
        sys.modules.pop(module_name, None)

    def _load_sandbox_skill_tools(self, meta: SkillMetadata, tools_py: Path) -> None:
        """Register tool schemas on host; execution is proxied to ephemeral Daytona sandboxes."""
        from local_agent.integrations.skill_runtime import invoke_skill_tool

        self._unload_skill_tools_module(meta.id)
        namespace: dict = {"__name__": f"skill_tools_{meta.id}", "__file__": str(tools_py)}
        source = tools_py.read_text(encoding="utf-8")
        exec(compile(source, str(tools_py), "exec"), namespace)  # noqa: S102
        tool_defs = namespace.get("TOOLS") or namespace.get("tools") or []
        skill_dir = tools_py.parent
        for td in tool_defs:
            if not isinstance(td, dict) or "name" not in td:
                continue
            short_name = td["name"]
            internal = f"skill.{meta.id}.{short_name}"
            schema = td.get("schema") or make_tool_schema(
                internal,
                td.get("description", ""),
                td.get("parameters", {}).get("properties", {}),
                td.get("parameters", {}).get("required"),
            )

            def _proxy(
                *,
                _skill_id: str = meta.id,
                _skill_dir: Path = skill_dir,
                _tool: str = short_name,
                **kwargs: object,
            ) -> str:
                return invoke_skill_tool(_skill_id, _skill_dir, _tool, dict(kwargs))

            self.tool_router.register_skill_tool(
                internal,
                short_name,
                _proxy,
                schema,
            )

    def _load_skill_tools(self, meta: SkillMetadata, tools_py: Path) -> None:
        module_name = f"skill_tools_{meta.id}"
        self._unload_skill_tools_module(meta.id)
        namespace: dict = {"__name__": module_name, "__file__": str(tools_py)}
        source = tools_py.read_text(encoding="utf-8")
        exec(compile(source, str(tools_py), "exec"), namespace)  # noqa: S102
        module = types.ModuleType(module_name)
        module.__dict__.update(namespace)
        sys.modules[module_name] = module
        tool_defs = namespace.get("TOOLS") or namespace.get("tools") or []
        for td in tool_defs:
            if isinstance(td, dict) and "name" in td:
                name = f"skill.{meta.id}.{td['name']}"
                fn = namespace.get(td["name"])
                schema = td.get("schema") or make_tool_schema(
                    name,
                    td.get("description", ""),
                    td.get("parameters", {}).get("properties", {}),
                    td.get("parameters", {}).get("required"),
                )
                if fn:
                    self.tool_router.register_skill_tool(
                        name,
                        td["name"],
                        fn,
                        schema,
                    )

    def _persist_skill(self, meta: SkillMetadata) -> None:
        row = self.session.get(SkillRow, meta.id)
        now = utcnow()
        if row:
            row.name = meta.name
            row.version = meta.version
            row.description = meta.description
            row.path = str(meta.path)
            row.tools = json.dumps(meta.tools, ensure_ascii=False)
            row.enabled = meta.enabled
        else:
            row = SkillRow(
                id=meta.id,
                name=meta.name,
                version=meta.version,
                description=meta.description,
                path=str(meta.path),
                tools=json.dumps(meta.tools, ensure_ascii=False),
                enabled=meta.enabled,
                registered_at=now,
            )
            self.session.add(row)
        self.session.commit()
