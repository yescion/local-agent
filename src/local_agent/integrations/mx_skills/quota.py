"""Daily call quota tracker for East Money MiaoXiang skill APIs."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass
class QuotaStatus:
    date: str
    used: int
    limit: int
    remaining: int
    enabled: bool = True

    def as_text(self) -> str:
        if not self.enabled:
            return "妙想金融工具包已禁用。"
        return (
            f"妙想工具今日配额：已用 {self.used}/{self.limit} 次，"
            f"剩余 {self.remaining} 次（次日 0 点恢复）。"
        )


@dataclass
class MxSkillsQuota:
    """Persisted daily quota — resets when the local calendar date changes."""

    quota_file: Path
    daily_limit: int = 50
    enabled: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def status(self) -> QuotaStatus:
        with self._lock:
            state = self._load_state()
            used = int(state.get("count", 0))
            limit = self.daily_limit
            return QuotaStatus(
                date=str(state.get("date", self._today())),
                used=used,
                limit=limit,
                remaining=max(0, limit - used),
                enabled=self.enabled,
            )

    def check(self) -> str | None:
        if not self.enabled:
            return "错误：妙想金融工具包未启用。"
        status = self.status()
        if status.remaining <= 0:
            return (
                f"错误：妙想工具今日调用次数已达上限（{status.limit} 次），"
                "请次日再试。可用 mx_quota_status 查看配额。"
            )
        return None

    def consume(self, tool_name: str) -> QuotaStatus:
        with self._lock:
            state = self._load_state()
            used = int(state.get("count", 0)) + 1
            history: list[dict[str, Any]] = list(state.get("history", []))
            history.append(
                {
                    "tool": tool_name,
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            if len(history) > 200:
                history = history[-200:]
            state = {
                "date": self._today(),
                "count": used,
                "history": history,
            }
            self._save_state(state)
            limit = self.daily_limit
            return QuotaStatus(
                date=state["date"],
                used=used,
                limit=limit,
                remaining=max(0, limit - used),
                enabled=self.enabled,
            )

    def _today(self) -> str:
        return date.today().isoformat()

    def _load_state(self) -> dict[str, Any]:
        today = self._today()
        if not self.quota_file.exists():
            return {"date": today, "count": 0, "history": []}
        try:
            raw = json.loads(self.quota_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"date": today, "count": 0, "history": []}
        if not isinstance(raw, dict):
            return {"date": today, "count": 0, "history": []}
        if raw.get("date") != today:
            return {"date": today, "count": 0, "history": []}
        return {
            "date": today,
            "count": int(raw.get("count", 0)),
            "history": raw.get("history", []) if isinstance(raw.get("history"), list) else [],
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        self.quota_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.quota_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.quota_file)
