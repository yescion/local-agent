"""Domain models for scheduled jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ScheduleType = Literal["cron", "once", "interval"]
ActionType = Literal["script", "skill_tool", "agent_prompt"]
JobStatus = Literal["pending", "running", "success", "error", "disabled"]


class ScheduledJob(BaseModel):
    id: str
    name: str = ""
    agent_id: str | None = None
    thread_id: str | None = None
    schedule_type: ScheduleType
    cron_expression: str | None = None
    at_time: datetime | None = None
    interval_minutes: int | None = None
    action_type: ActionType
    action_payload: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    max_runs: int | None = None
    run_count: int = 0
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_status: JobStatus | None = None
    last_error: str | None = None
    timeout_secs: int = 300
    created_at: datetime
    updated_at: datetime


class JobRun(BaseModel):
    id: str
    job_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: JobStatus
    output: str | None = None
    error: str | None = None
