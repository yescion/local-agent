"""Execute scheduled job actions on the host."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from local_agent.jobs.models import ScheduledJob
from local_agent.skills.loader import parse_skill_md

if TYPE_CHECKING:
    from local_agent.agent.manager import AgentManager

logger = logging.getLogger(__name__)

_MAX_OUTPUT_CHARS = 50_000


class JobExecutor:
    def __init__(
        self,
        *,
        data_dir: Path,
        write_paths: list[Path],
        skill_directories: list[Path],
        manager_factory: Callable[[], AgentManager],
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.write_paths = [p.resolve() for p in write_paths]
        self.skill_directories = skill_directories
        self._manager_factory = manager_factory

    def _allowed_roots(self) -> list[Path]:
        roots = {self.data_dir, *self.write_paths}
        return sorted(roots)

    def validate_script_path(self, path: str) -> Path:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"脚本不存在 — {path}")
        if resolved.suffix.lower() not in {".py", ".bat", ".cmd", ".ps1"}:
            raise ValueError("仅允许执行 .py / .bat / .cmd / .ps1 脚本")
        for root in self._allowed_roots():
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        allowed = ", ".join(str(r) for r in self._allowed_roots())
        raise ValueError(f"脚本路径不在白名单内（允许: {allowed}）— {path}")

    def _host_skill_ids(self) -> set[str]:
        ids: set[str] = set()
        for directory in self.skill_directories:
            if not directory.is_dir():
                continue
            for skill_md in directory.rglob("SKILL.md"):
                try:
                    meta = parse_skill_md(skill_md)
                except Exception:
                    continue
                if meta.enabled and meta.execution == "host":
                    ids.add(meta.id)
        return ids

    def execute(self, job: ScheduledJob) -> tuple[str, str | None]:
        try:
            if job.action_type == "script":
                return self._run_script(job), None
            if job.action_type == "skill_tool":
                return self._run_skill_tool(job), None
            if job.action_type == "agent_prompt":
                return self._run_agent_prompt(job), None
            return "", f"未知动作类型: {job.action_type}"
        except Exception as e:
            logger.exception("Job %s execution failed", job.id)
            return "", str(e)

    def _run_script(self, job: ScheduledJob) -> str:
        path_value = str(job.action_payload.get("path") or job.action_payload.get("script_path") or "")
        script = self.validate_script_path(path_value)
        timeout = max(1, job.timeout_secs)
        args = job.action_payload.get("args") or []
        if not isinstance(args, list):
            args = []

        if script.suffix.lower() == ".py":
            cmd = [sys.executable, str(script), *[str(a) for a in args]]
        elif script.suffix.lower() in {".bat", ".cmd"}:
            cmd = ["cmd", "/c", str(script), *[str(a) for a in args]]
        else:
            cmd = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                *[str(a) for a in args],
            ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(script.parent),
        )
        output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
        output = output.strip()
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + "\n...[截断]"
        if result.returncode != 0:
            raise RuntimeError(f"退出码 {result.returncode}\n{output}")
        return output or "(无输出)"

    def _run_skill_tool(self, job: ScheduledJob) -> str:
        skill_id = str(job.action_payload.get("skill_id") or "").strip()
        tool_name = str(job.action_payload.get("tool_name") or "").strip()
        if not skill_id or not tool_name:
            raise ValueError("skill_tool 动作须提供 skill_id 与 tool_name")
        if skill_id not in self._host_skill_ids():
            raise ValueError(
                f"技能 {skill_id} 不是宿主机执行技能（execution: host），"
                "定时任务不能调用沙盒技能"
            )

        arguments = job.action_payload.get("arguments") or {}
        if isinstance(arguments, str):
            arguments = json.loads(arguments) if arguments.strip() else {}

        manager = self._manager_factory()
        session = manager._session()
        try:
            registry = manager._build_skill_registry(session)
            internal = f"skill.{skill_id}.{tool_name}"
            handler = registry.tool_router._handlers.get(internal)
            if handler is None:
                raise ValueError(f"未找到工具 {tool_name}（技能 {skill_id}）")
            result = handler(**arguments)
            output = str(result)
            if len(output) > _MAX_OUTPUT_CHARS:
                output = output[:_MAX_OUTPUT_CHARS] + "\n...[截断]"
            return output
        finally:
            session.close()

    def _run_agent_prompt(self, job: ScheduledJob) -> str:
        prompt = str(job.action_payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("agent_prompt 动作须提供 prompt")
        agent_id = job.agent_id or str(job.action_payload.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("agent_prompt 须提供 agent_id")
        thread_id = job.thread_id or job.action_payload.get("thread_id")

        manager = self._manager_factory()
        runtime = manager.get_or_create_runtime(agent_id, thread_id)
        runtime.run_background_iteration(prompt)
        return f"已在 agent {agent_id} 上执行后台 prompt（{datetime.now(timezone.utc).isoformat()}）"
