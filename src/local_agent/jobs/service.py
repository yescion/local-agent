"""Job scheduler service facade for tools and CLI wiring."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session, sessionmaker

from local_agent.jobs.cron_utils import compute_next_run, parse_cron_preview
from local_agent.jobs.executor import JobExecutor
from local_agent.tools.session_context import resolve_session_ids
from local_agent.jobs.models import ScheduledJob
from local_agent.jobs.scheduler import HostJobScheduler
from local_agent.storage.models import format_local_datetime
from local_agent.storage.repositories.job_repo import JobRepository

if TYPE_CHECKING:
    from local_agent.agent.manager import AgentManager
    from local_agent.config.models import Settings

logger = logging.getLogger(__name__)

_scheduler: HostJobScheduler | None = None
_service: JobService | None = None


class JobService:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        manager_factory: Callable[[], AgentManager],
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self._manager_factory = manager_factory
        self._executor = JobExecutor(
            data_dir=settings.app.data_dir,
            write_paths=settings.tools.write_paths,
            skill_directories=settings.skills.directories,
            manager_factory=manager_factory,
        )

    def _repo(self) -> tuple[Session, JobRepository]:
        session = self._session_factory()
        return session, JobRepository(session)

    def create_job(
        self,
        *,
        name: str = "",
        schedule_type: str,
        action_type: str,
        action_payload: dict[str, Any],
        agent_id: str | None = None,
        thread_id: str | None = None,
        cron_expression: str | None = None,
        at_time: str | None = None,
        interval_minutes: int | None = None,
        max_runs: int | None = None,
        timeout_secs: int | None = None,
    ) -> str:
        schedule_type = schedule_type.strip().lower()
        action_type = action_type.strip().lower()
        if schedule_type not in ("cron", "once", "interval"):
            return json.dumps({"error": f"无效 schedule_type: {schedule_type}"}, ensure_ascii=False)
        if action_type not in ("script", "skill_tool", "agent_prompt"):
            return json.dumps({"error": f"无效 action_type: {action_type}"}, ensure_ascii=False)

        timeout = timeout_secs or self.settings.jobs.default_timeout_secs
        timeout = max(1, min(timeout, 3600))

        parsed_at: datetime | None = None
        if schedule_type == "once":
            if not at_time:
                return json.dumps({"error": "once 调度须提供 at_time (YYYY-MM-DD HH:MM:SS)"}, ensure_ascii=False)
            try:
                local_tz = datetime.now().astimezone().tzinfo
                parsed_at = (
                    datetime.strptime(at_time, "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=local_tz)
                    .astimezone(timezone.utc)
                )
            except ValueError:
                return json.dumps({"error": f"at_time 格式无效: {at_time}"}, ensure_ascii=False)
            if parsed_at <= datetime.now(timezone.utc):
                return json.dumps({"error": f"at_time 已过: {at_time}"}, ensure_ascii=False)
        elif schedule_type == "cron":
            if not cron_expression:
                return json.dumps({"error": "cron 调度须提供 cron_expression"}, ensure_ascii=False)
        elif schedule_type == "interval":
            if not interval_minutes or interval_minutes < 1:
                return json.dumps({"error": "interval 调度须提供 interval_minutes >= 1"}, ensure_ascii=False)
            interval_minutes = min(interval_minutes, 24 * 60)

        payload = dict(action_payload)
        if action_type == "script":
            path = str(payload.get("path") or payload.get("script_path") or "").strip()
            if not path:
                return json.dumps({"error": "script 动作须提供 path 或 script_path"}, ensure_ascii=False)
            try:
                self._executor.validate_script_path(path)
            except ValueError as e:
                return json.dumps({"error": str(e)}, ensure_ascii=False)
            payload["path"] = path
        elif action_type == "skill_tool":
            skill_id = str(payload.get("skill_id") or "").strip()
            tool_name = str(payload.get("tool_name") or "").strip()
            if not skill_id or not tool_name:
                return json.dumps({"error": "skill_tool 须提供 skill_id 与 tool_name"}, ensure_ascii=False)
            if skill_id not in self._executor._host_skill_ids():
                return json.dumps(
                    {
                        "error": f"技能 {skill_id} 不是 execution:host，"
                        "定时任务只能调用宿主机技能（如 loc_kline、web_search）",
                    },
                    ensure_ascii=False,
                )
        elif action_type == "agent_prompt":
            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                return json.dumps({"error": "agent_prompt 须提供 prompt"}, ensure_ascii=False)
            effective_agent = agent_id or payload.get("agent_id")
            if not effective_agent:
                return json.dumps({"error": "agent_prompt 须提供 agent_id"}, ensure_ascii=False)
            agent_id = str(effective_agent)

        script_path_for_infer = None
        if action_type == "script":
            script_path_for_infer = str(payload.get("path") or "")
        agent_id, thread_id = resolve_session_ids(
            agent_id=agent_id,
            thread_id=thread_id,
            artifact_path=script_path_for_infer,
        )

        try:
            next_run = compute_next_run(
                schedule_type=schedule_type,
                base=datetime.now(timezone.utc),
                cron_expression=cron_expression,
                at_time=parsed_at,
                interval_minutes=interval_minutes,
            )
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        session, repo = self._repo()
        try:
            job = repo.create(
                name=name or f"{action_type}-{schedule_type}",
                schedule_type=schedule_type,
                action_type=action_type,
                action_payload=payload,
                agent_id=agent_id,
                thread_id=thread_id,
                cron_expression=cron_expression,
                at_time=parsed_at,
                interval_minutes=interval_minutes,
                max_runs=max_runs,
                timeout_secs=timeout,
                next_run_at=next_run,
            )
            return json.dumps(self._job_summary(job), ensure_ascii=False, indent=2)
        finally:
            session.close()

    def list_jobs(self, *, enabled_only: bool = False) -> str:
        session, repo = self._repo()
        try:
            jobs = repo.list_all(enabled_only=enabled_only)
            return json.dumps(
                [self._job_summary(j) for j in jobs],
                ensure_ascii=False,
                indent=2,
            )
        finally:
            session.close()

    def list_jobs_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        session, repo = self._repo()
        try:
            jobs = repo.list_by_thread(thread_id.strip())
            return [self._job_summary(j) for j in jobs]
        finally:
            session.close()

    def get_job_runs(self, job_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        session, repo = self._repo()
        try:
            runs = repo.list_runs(job_id.strip(), limit=limit)
            return [
                {
                    "id": r.id,
                    "status": r.status,
                    "started_at": format_local_datetime(r.started_at),
                    "finished_at": format_local_datetime(r.finished_at),
                    "output": (r.output or "")[:2000],
                    "error": r.error,
                }
                for r in runs
            ]
        finally:
            session.close()

    def get_job(self, job_id: str) -> str:
        session, repo = self._repo()
        try:
            job = repo.get(job_id.strip())
            if not job:
                return json.dumps({"error": f"未找到任务 — {job_id}"}, ensure_ascii=False)
            return json.dumps(self._job_summary(job), ensure_ascii=False, indent=2)
        finally:
            session.close()

    def cancel_job(self, job_id: str, *, delete: bool = False) -> str:
        session, repo = self._repo()
        try:
            if delete:
                ok = repo.delete(job_id.strip())
                if not ok:
                    return json.dumps({"error": f"未找到任务 — {job_id}"}, ensure_ascii=False)
                return json.dumps({"status": "deleted", "job_id": job_id}, ensure_ascii=False)
            job = repo.set_enabled(job_id.strip(), False)
            if not job:
                return json.dumps({"error": f"未找到任务 — {job_id}"}, ensure_ascii=False)
            return json.dumps(self._job_summary(job), ensure_ascii=False, indent=2)
        finally:
            session.close()

    def job_logs(self, job_id: str, limit: int = 10) -> str:
        session, repo = self._repo()
        try:
            job = repo.get(job_id.strip())
            if not job:
                return json.dumps({"error": f"未找到任务 — {job_id}"}, ensure_ascii=False)
            runs = repo.list_runs(job_id.strip(), limit=limit)
            return json.dumps(
                {
                    "job_id": job_id,
                    "job_name": job.name,
                    "runs": [
                        {
                            "id": r.id,
                            "status": r.status,
                            "started_at": format_local_datetime(r.started_at),
                            "finished_at": format_local_datetime(r.finished_at),
                            "output": (r.output or "")[:2000],
                            "error": r.error,
                        }
                        for r in runs
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        finally:
            session.close()

    def parse_cron(self, cron_expression: str, count: int = 5) -> str:
        try:
            result = parse_cron_preview(cron_expression, count=count)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except ImportError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @staticmethod
    def _job_summary(job: ScheduledJob) -> dict[str, Any]:
        return {
            "id": job.id,
            "name": job.name,
            "enabled": job.enabled,
            "schedule_type": job.schedule_type,
            "cron_expression": job.cron_expression,
            "at_time": format_local_datetime(job.at_time) if job.at_time else None,
            "interval_minutes": job.interval_minutes,
            "action_type": job.action_type,
            "action_payload": job.action_payload,
            "agent_id": job.agent_id,
            "thread_id": job.thread_id,
            "max_runs": job.max_runs,
            "run_count": job.run_count,
            "next_run_at": format_local_datetime(job.next_run_at) if job.next_run_at else None,
            "last_run_at": format_local_datetime(job.last_run_at) if job.last_run_at else None,
            "last_status": job.last_status,
            "last_error": job.last_error,
            "timeout_secs": job.timeout_secs,
        }


def configure_job_scheduler(
    settings: Settings,
    session_factory: sessionmaker[Session],
    manager_factory: Callable[[], AgentManager],
) -> None:
    global _scheduler, _service
    _service = JobService(settings, session_factory, manager_factory)
    _scheduler = HostJobScheduler(
        settings.jobs,
        session_factory,
        _service._executor,
    )
    _scheduler.start()


def get_job_service() -> JobService:
    if _service is None:
        raise RuntimeError("Job scheduler 未初始化")
    return _service


def stop_job_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None
