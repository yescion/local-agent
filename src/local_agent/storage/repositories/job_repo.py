"""Scheduled job repository."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from local_agent.jobs.models import JobRun, ScheduledJob
from local_agent.storage.models import JobRunRow, ScheduledJobRow, parse_utc, utcnow


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        return parse_utc(value)

    def _job_from_row(self, row: ScheduledJobRow) -> ScheduledJob:
        return ScheduledJob(
            id=row.id,
            name=row.name or "",
            agent_id=row.agent_id,
            thread_id=row.thread_id,
            schedule_type=row.schedule_type,  # type: ignore[arg-type]
            cron_expression=row.cron_expression,
            at_time=self._parse_dt(row.at_time),
            interval_minutes=row.interval_minutes,
            action_type=row.action_type,  # type: ignore[arg-type]
            action_payload=json.loads(row.action_payload or "{}"),
            enabled=bool(row.enabled),
            max_runs=row.max_runs,
            run_count=row.run_count or 0,
            next_run_at=self._parse_dt(row.next_run_at),
            last_run_at=self._parse_dt(row.last_run_at),
            last_status=row.last_status,  # type: ignore[arg-type]
            last_error=row.last_error,
            timeout_secs=row.timeout_secs or 300,
            created_at=parse_utc(row.created_at),
            updated_at=parse_utc(row.updated_at),
        )

    def _run_from_row(self, row: JobRunRow) -> JobRun:
        return JobRun(
            id=row.id,
            job_id=row.job_id,
            started_at=parse_utc(row.started_at),
            finished_at=self._parse_dt(row.finished_at),
            status=row.status,  # type: ignore[arg-type]
            output=row.output,
            error=row.error,
        )

    def create(
        self,
        *,
        name: str,
        schedule_type: str,
        action_type: str,
        action_payload: dict[str, Any],
        agent_id: str | None = None,
        thread_id: str | None = None,
        cron_expression: str | None = None,
        at_time: datetime | None = None,
        interval_minutes: int | None = None,
        max_runs: int | None = None,
        timeout_secs: int = 300,
        next_run_at: datetime | None = None,
        enabled: bool = True,
    ) -> ScheduledJob:
        now = utcnow()
        row = ScheduledJobRow(
            id=str(uuid.uuid4()),
            name=name,
            agent_id=agent_id,
            thread_id=thread_id,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            at_time=at_time.isoformat() if at_time else None,
            interval_minutes=interval_minutes,
            action_type=action_type,
            action_payload=json.dumps(action_payload, ensure_ascii=False),
            enabled=enabled,
            max_runs=max_runs,
            run_count=0,
            next_run_at=next_run_at.isoformat() if next_run_at else None,
            timeout_secs=timeout_secs,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        self.session.commit()
        return self._job_from_row(row)

    def get(self, job_id: str) -> ScheduledJob | None:
        row = self.session.get(ScheduledJobRow, job_id)
        return self._job_from_row(row) if row else None

    def list_all(self, *, enabled_only: bool = False) -> list[ScheduledJob]:
        stmt = select(ScheduledJobRow).order_by(ScheduledJobRow.created_at.desc())
        if enabled_only:
            stmt = stmt.where(ScheduledJobRow.enabled.is_(True))
        rows = self.session.scalars(stmt).all()
        return [self._job_from_row(r) for r in rows]

    def list_by_thread(
        self, thread_id: str, *, enabled_only: bool = False
    ) -> list[ScheduledJob]:
        stmt = (
            select(ScheduledJobRow)
            .where(ScheduledJobRow.thread_id == thread_id)
            .order_by(ScheduledJobRow.created_at.desc())
        )
        if enabled_only:
            stmt = stmt.where(ScheduledJobRow.enabled.is_(True))
        rows = self.session.scalars(stmt).all()
        return [self._job_from_row(r) for r in rows]

    def list_due(self, now: datetime) -> list[ScheduledJob]:
        now_s = now.isoformat()
        rows = self.session.scalars(
            select(ScheduledJobRow).where(
                ScheduledJobRow.enabled.is_(True),
                ScheduledJobRow.next_run_at.is_not(None),
                ScheduledJobRow.next_run_at <= now_s,
            )
        ).all()
        return [self._job_from_row(r) for r in rows]

    def update(self, job: ScheduledJob) -> ScheduledJob:
        row = self.session.get(ScheduledJobRow, job.id)
        if not row:
            raise KeyError(f"Job not found: {job.id}")
        row.name = job.name
        row.agent_id = job.agent_id
        row.thread_id = job.thread_id
        row.schedule_type = job.schedule_type
        row.cron_expression = job.cron_expression
        row.at_time = job.at_time.isoformat() if job.at_time else None
        row.interval_minutes = job.interval_minutes
        row.action_type = job.action_type
        row.action_payload = json.dumps(job.action_payload, ensure_ascii=False)
        row.enabled = job.enabled
        row.max_runs = job.max_runs
        row.run_count = job.run_count
        row.next_run_at = job.next_run_at.isoformat() if job.next_run_at else None
        row.last_run_at = job.last_run_at.isoformat() if job.last_run_at else None
        row.last_status = job.last_status
        row.last_error = job.last_error
        row.timeout_secs = job.timeout_secs
        row.updated_at = utcnow()
        self.session.commit()
        return self._job_from_row(row)

    def set_enabled(self, job_id: str, enabled: bool) -> ScheduledJob | None:
        row = self.session.get(ScheduledJobRow, job_id)
        if not row:
            return None
        row.enabled = enabled
        row.updated_at = utcnow()
        if not enabled:
            row.last_status = "disabled"
        self.session.commit()
        return self._job_from_row(row)

    def delete(self, job_id: str) -> bool:
        row = self.session.get(ScheduledJobRow, job_id)
        if not row:
            return False
        self.session.execute(delete(JobRunRow).where(JobRunRow.job_id == job_id))
        self.session.delete(row)
        self.session.commit()
        return True

    def add_run(
        self,
        job_id: str,
        *,
        status: str,
        output: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> JobRun:
        row = JobRunRow(
            id=str(uuid.uuid4()),
            job_id=job_id,
            started_at=(started_at or datetime.now()).isoformat(),
            finished_at=finished_at.isoformat() if finished_at else None,
            status=status,
            output=output,
            error=error,
        )
        self.session.add(row)
        self.session.commit()
        return self._run_from_row(row)

    def list_runs(self, job_id: str, *, limit: int = 20) -> list[JobRun]:
        limit = min(max(1, limit), 100)
        rows = self.session.scalars(
            select(JobRunRow)
            .where(JobRunRow.job_id == job_id)
            .order_by(JobRunRow.started_at.desc())
            .limit(limit)
        ).all()
        return [self._run_from_row(r) for r in rows]
