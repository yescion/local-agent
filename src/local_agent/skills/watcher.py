"""Poll skill directories and trigger reload on file changes."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillAutoReloader:
    """Watch skill directories via mtime polling and invoke a reload callback."""

    _WATCH_NAMES = ("SKILL.md", "tools.py")

    def __init__(
        self,
        directories: list[Path],
        on_reload: Callable[[], None],
        interval_secs: float = 1.0,
        debounce_secs: float = 0.3,
    ) -> None:
        self.directories = directories
        self.on_reload = on_reload
        self.interval_secs = interval_secs
        self.debounce_secs = debounce_secs
        self._snapshots: dict[Path, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending_reload = False
        self._last_reload_at = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._snapshots = self._collect_snapshots()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="skill-auto-reload", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_secs + 1)
            self._thread = None

    def _collect_snapshots(self) -> dict[Path, float]:
        snapshots: dict[Path, float] = {}
        for directory in self.directories:
            if not directory.exists():
                continue
            for name in self._WATCH_NAMES:
                for path in directory.rglob(name):
                    try:
                        snapshots[path.resolve()] = path.stat().st_mtime
                    except OSError:
                        continue
        return snapshots

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_secs):
            current = self._collect_snapshots()
            if current != self._snapshots:
                self._snapshots = current
                self._pending_reload = True

            if not self._pending_reload:
                continue

            now = time.monotonic()
            if now - self._last_reload_at < self.debounce_secs:
                continue

            self._pending_reload = False
            self._last_reload_at = now
            try:
                self.on_reload()
            except Exception:
                logger.exception("Skill auto-reload callback failed")
