from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass

from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.runtime.loop import RuntimeLoop, RuntimeLoopConfig


@dataclass(frozen=True, slots=True)
class BackgroundRuntimeConfig:
    """Configuration for the codexx-owned background maintenance queue."""

    enabled: bool = True
    tick_interval_seconds: float = 2.0
    hook_limit: int = 20
    exit_flush_seconds: float = 3.0

    @classmethod
    def from_env(cls) -> "BackgroundRuntimeConfig":
        return cls(
            enabled=_env_bool("ADVANCED_AGENT_CODEXX_BACKGROUND_MAINTENANCE", True),
            tick_interval_seconds=_env_float("ADVANCED_AGENT_CODEXX_MAINTENANCE_TICK", 2.0),
            hook_limit=_env_int("ADVANCED_AGENT_CODEXX_MAINTENANCE_HOOK_LIMIT", 20),
            exit_flush_seconds=_env_float("ADVANCED_AGENT_CODEXX_EXIT_FLUSH_SECONDS", 3.0),
        )


class BackgroundRuntimeQueue:
    """Run runtime hooks in a small background thread while codexx is alive.

    This consumes the same `runtime_hooks` queue as `advanced-agentd`, but is
    scoped to the lifetime of one interactive codexx process. Request-time prompt
    injection remains tool-driven; this queue only processes deterministic
    maintenance hooks such as memory/profile/compaction work.
    """

    def __init__(self, app: RuntimeApp, config: BackgroundRuntimeConfig | None = None) -> None:
        self.app = app
        self.config = config or BackgroundRuntimeConfig.from_env()
        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> BaseException | None:
        return self._error

    def start(self) -> None:
        if not self.config.enabled or self.running:
            return
        self._stop.clear()
        self._started.clear()
        self._thread = threading.Thread(target=self._thread_main, name="advanced-agent-bg-runtime", daemon=True)
        self._thread.start()
        self._started.wait(timeout=2.0)

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.config.exit_flush_seconds + 2.0))
        if self._thread.is_alive():
            self.app.events.publish(
                "runtime.background.stop_timeout",
                "background_runtime",
                {"exit_flush_seconds": self.config.exit_flush_seconds},
            )
            return
        self._thread = None

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run_async())
        except BaseException as exc:  # pragma: no cover - defensive runtime guard
            self._error = exc
            self.app.events.publish("runtime.background.error", "background_runtime", {"error": str(exc), "type": type(exc).__name__})
            self._started.set()

    async def _run_async(self) -> None:
        loop = RuntimeLoop(
            self.app,
            RuntimeLoopConfig(
                tick_interval_seconds=self.config.tick_interval_seconds,
                hook_limit=self.config.hook_limit,
            ),
        )
        await loop.start()
        self.app.events.publish("runtime.background.started", "background_runtime", {"tick_interval_seconds": self.config.tick_interval_seconds})
        self._started.set()
        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.05)
        finally:
            await loop.stop(timeout_seconds=max(0.5, min(2.0, self.config.exit_flush_seconds or 0.5)))
            await self._flush_due_hooks(loop)
            self.app.events.publish("runtime.background.stopped", "background_runtime", {})

    async def _flush_due_hooks(self, loop: RuntimeLoop) -> None:
        deadline = time.monotonic() + max(0.0, self.config.exit_flush_seconds)
        while time.monotonic() < deadline:
            result = await loop.tick_once()
            if result.fired == 0:
                break


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
