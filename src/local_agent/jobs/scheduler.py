"""Background thread that fires due scheduled jobs."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session, sessionmaker

from local_agent.artifacts.manager import ArtifactManager
from local_agent.jobs.cron_utils import compute_next_run
from local_agent.jobs.executor import JobExecutor
from local_agent.jobs.models import ScheduledJob
from local_agent.storage.repositories.job_repo import JobRepository

if TYPE_CHECKING:
    from local_agent.config.models import JobSchedulerConfig

logger = logging.getLogger(__name__)


class HostJobScheduler:
    def __init__(
        self,
        config: JobSchedulerConfig,
        session_factory: sessionmaker[Session],
        executor: JobExecutor,
    ) -> None:
        self.config = config
        self._session_factory = session_factory
        self._executor = executor
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running_jobs = 0
        self._jobs_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if not self.config.enabled:
            return
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="host-job-scheduler", daemon=True)
        self._thread.start()
        logger.info("Host job scheduler started (poll=%ss)", self.config.poll_interval_secs)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("Job scheduler tick failed")
            self._stop_event.wait(self.config.poll_interval_secs)

    def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        session = self._session_factory()
        try:
            repo = JobRepository(session)
            due_jobs = repo.list_due(now)
        finally:
            session.close()

        for job in due_jobs:
            if self._stop_event.is_set():
                break
            with self._jobs_lock:
                if self._running_jobs >= self.config.max_concurrent_jobs:
                    break
                self._running_jobs += 1
            threading.Thread(
                target=self._run_job_safe,
                args=(job.id,),
                name=f"job-{job.id[:8]}",
                daemon=True,
            ).start()

    def _run_job_safe(self, job_id: str) -> None:
        try:
            self._run_job(job_id)
        finally:
            with self._jobs_lock:
                self._running_jobs = max(0, self._running_jobs - 1)

    def _run_job(self, job_id: str) -> None:
        session = self._session_factory()
        try:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if not job or not job.enabled:
                return
            if job.next_run_at and job.next_run_at > datetime.now(timezone.utc):
                return

            started = datetime.now(timezone.utc)
            job.last_status = "running"
            repo.update(job)

            output, error = self._executor.execute(job)
            finished = datetime.now(timezone.utc)

            job.run_count += 1
            job.last_run_at = finished
            if error:
                job.last_status = "error"
                job.last_error = error
                status = "error"
            else:
                job.last_status = "success"
                job.last_error = None
                status = "success"

            repo.add_run(
                job_id,
                status=status,
                output=output or None,
                error=error,
                started_at=started,
                finished_at=finished,
            )
            if status == "success" and job.agent_id and job.thread_id:
                self._sync_job_artifacts(job.agent_id, job.thread_id)
            self._advance_schedule(job, finished)
            repo.update(job)
        finally:
            session.close()

    def _sync_job_artifacts(self, agent_id: str, thread_id: str) -> None:
        try:
            manager = self._executor._manager_factory()
            session = manager._session()
            try:
                ArtifactManager(session, manager.artifacts_dir).sync_thread_artifacts(
                    agent_id, thread_id
                )
            finally:
                session.close()
        except Exception:
            logger.exception(
                "Failed to sync artifacts after job (agent=%s thread=%s)",
                agent_id,
                thread_id,
            )

    def _advance_schedule(self, job: ScheduledJob, finished: datetime) -> None:
        if job.schedule_type == "once":
            job.enabled = False
            job.next_run_at = None
            return

        if job.max_runs is not None and job.run_count >= job.max_runs:
            job.enabled = False
            job.next_run_at = None
            job.last_status = "disabled"
            return

        try:
            job.next_run_at = compute_next_run(
                schedule_type=job.schedule_type,
                base=finished,
                cron_expression=job.cron_expression,
                at_time=job.at_time,
                interval_minutes=job.interval_minutes,
            )
        except Exception as e:
            job.enabled = False
            job.next_run_at = None
            job.last_status = "error"
            job.last_error = f"计算下次执行时间失败: {e}"
