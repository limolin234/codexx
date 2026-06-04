from __future__ import annotations

import asyncio
from dataclasses import dataclass

from advanced_agent.automation import AutomationResult
from advanced_agent.runtime.app import RuntimeApp


@dataclass(slots=True)
class RuntimeLoopConfig:
    tick_interval_seconds: float = 1.0
    hook_limit: int = 20
    publish_idle_ticks: bool = False


class RuntimeLoop:
    """Async background loop for deterministic runtime maintenance.

    The loop is intentionally small: it owns no business logic. It only wakes
    deterministic engines such as AutomationEngine, publishes runtime lifecycle
    events, and provides graceful start/stop semantics. Event-driven wakeups can
    be layered on this later without changing workers or stores.
    """

    def __init__(self, app: RuntimeApp, config: RuntimeLoopConfig | None = None) -> None:
        self.app = app
        self.config = config or RuntimeLoopConfig()
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False
        self._last_result: AutomationResult | None = None

    @property
    def running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    @property
    def last_result(self) -> AutomationResult | None:
        return self._last_result

    async def tick_once(self, *, shutdown_flush: bool = False) -> AutomationResult:
        result = self.app.automation.tick(limit=self.config.hook_limit, shutdown_flush=shutdown_flush)
        self._last_result = result
        if result.fired or self.config.publish_idle_ticks:
            self.app.events.publish(
                "runtime.tick",
                "runtime_loop",
                {"fired": result.fired, "actions": result.actions},
            )
        return result

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="advanced-agent-runtime-loop")
        # Give the task one scheduling opportunity so startup errors surface in
        # tests and embedding applications can observe `running` immediately.
        await asyncio.sleep(0)

    async def stop(self, timeout_seconds: float = 5.0) -> None:
        if self._task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        finally:
            self._running = False
            self._task = None
            self._stop_event = None

    async def _run(self) -> None:
        assert self._stop_event is not None
        self._running = True
        self.app.events.publish("runtime.loop.started", "runtime_loop", {})
        try:
            while not self._stop_event.is_set():
                try:
                    await self.tick_once()
                except Exception as exc:  # pragma: no cover - defensive runtime guard
                    self.app.events.publish("runtime.loop.error", "runtime_loop", {"error": str(exc), "type": type(exc).__name__})
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.tick_interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False
            self.app.events.publish("runtime.loop.stopped", "runtime_loop", {})
