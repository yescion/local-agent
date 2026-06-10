"""Cron expression helpers."""

from __future__ import annotations

from datetime import datetime

try:
    from croniter import croniter
except ImportError:
    croniter = None  # type: ignore[assignment,misc]


def ensure_croniter() -> None:
    if croniter is None:
        raise ImportError("croniter 未安装，请运行: pip install croniter")


def compute_next_run(
    *,
    schedule_type: str,
    base: datetime,
    cron_expression: str | None = None,
    at_time: datetime | None = None,
    interval_minutes: int | None = None,
) -> datetime | None:
    if schedule_type == "once":
        return at_time
    if schedule_type == "interval":
        minutes = interval_minutes or 1
        from datetime import timedelta

        return base + timedelta(minutes=minutes)
    if schedule_type == "cron":
        ensure_croniter()
        if not cron_expression:
            raise ValueError("cron 调度须提供 cron_expression")
        return croniter(cron_expression, base).get_next(datetime)
    raise ValueError(f"未知调度类型: {schedule_type}")


def parse_cron_preview(cron_expression: str, count: int = 5) -> dict:
    ensure_croniter()
    count = min(max(1, count), 20)
    base = datetime.now()
    try:
        cron = croniter(cron_expression, base)
    except (ValueError, KeyError) as e:
        return {"error": f"cron 表达式无效: {e}", "cron_expression": cron_expression}
    times = [cron.get_next(datetime).strftime("%Y-%m-%d %H:%M:%S") for _ in range(count)]
    return {
        "cron_expression": cron_expression,
        "next_run_times": times,
        "total_shown": len(times),
        "current_time": base.strftime("%Y-%m-%d %H:%M:%S"),
    }
