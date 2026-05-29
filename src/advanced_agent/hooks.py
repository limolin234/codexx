from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from advanced_agent.time_service import TimeService


class HookKind(StrEnum):
    WAKE = "wake"
    CHECK_STATE = "check_state"
    CHECK_TASKS = "check_tasks"
    PREFERENCE_MAINTENANCE = "preference_maintenance"
    MEMORY_INDEX = "memory_index"
    COMPACT_MEMORY = "compact_memory"
    MEMORY_MAINTENANCE = "memory_maintenance"
    RAW_RETENTION = "raw_retention"
    SLEEP = "sleep"


@dataclass(slots=True)
class HookSpec:
    kind: str
    target: str
    wake_at_ms: int
    payload: dict = field(default_factory=dict)
    repeat_ms: int | None = None
    enabled: bool = True
    id: str = field(default_factory=lambda: f"hook_{uuid4().hex}")


class HookScheduler:
    """Deterministic built-in hook scheduler.

    Hooks usually wake main-agent for an internal state check. Waking does not
    imply speaking to the user. Main-agent may trigger interactive-agent only
    when user-visible output is necessary. Models should request hooks; the
    runtime owns actual wake/sleep timing. This prevents LLMs from inventing
    unreliable timers in text.
    """

    def __init__(self, time: TimeService) -> None:
        self.time = time
        self.hooks: dict[str, HookSpec] = {}

    def schedule_in(self, kind: HookKind, target: str, delay_ms: int, payload: dict | None = None, repeat_ms: int | None = None) -> HookSpec:
        hook = HookSpec(kind=kind, target=target, wake_at_ms=self.time.wall_ms() + delay_ms, payload=payload or {}, repeat_ms=repeat_ms)
        self.hooks[hook.id] = hook
        return hook

    def due(self) -> list[HookSpec]:
        now = self.time.wall_ms()
        ready = [hook for hook in self.hooks.values() if hook.enabled and hook.wake_at_ms <= now]
        for hook in ready:
            if hook.repeat_ms is None:
                hook.enabled = False
            else:
                hook.wake_at_ms = now + hook.repeat_ms
        return ready

    def sleep_backoff_for_idle(self, idle_ms: int) -> int:
        """Return next main-agent check delay for an idle session.

        This is an internal wake-up interval, not a user notification interval.
        """
        if idle_ms < 60_000:
            return 60_000
        if idle_ms < 10 * 60_000:
            return 5 * 60_000
        if idle_ms < 60 * 60_000:
            return 30 * 60_000
        return 3 * 60 * 60_000
