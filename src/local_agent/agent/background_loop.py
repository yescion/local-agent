"""Background timed loop service (Stage 7)."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from local_agent.agent.runtime import AgentRuntime


class BackgroundLoopService:
    def __init__(self, sleep_slice_secs: int = 1) -> None:
        self.sleep_slice_secs = sleep_slice_secs
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._prompt = ""
        self._interval_mins = 10

    @property
    def is_running(self) -> bool:
        return self._running

    def start(
        self,
        prompt: str,
        interval_mins: int,
        run_fn: Callable[[str], None],
        on_start: Callable[[str, int], None] | None = None,
    ) -> None:
        if self._running:
            self.stop()
        self._stop_event.clear()
        self._prompt = prompt
        self._interval_mins = interval_mins
        self._running = True

        def _loop() -> None:
            if on_start:
                on_start(prompt, interval_mins)
            total_secs = interval_mins * 60
            elapsed = 0
            while not self._stop_event.is_set():
                if elapsed >= total_secs:
                    try:
                        run_fn(prompt)
                    except Exception as e:
                        print(f"\n[SYSTEM] Loop error: {e}")
                    elapsed = 0
                self._stop_event.wait(self.sleep_slice_secs)
                elapsed += self.sleep_slice_secs
            self._running = False

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._running = False
        self._thread = None
