from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from advanced_agent.models import AuditRequest, AuditResult, InteractionState, MainVisibleState, Message, StreamDelta, TaskSpec, TaskState


class TimeContext(Protocol):
    def wall_ms(self) -> int: ...
    def monotonic_ms(self) -> int: ...
    def wall_iso(self) -> str: ...


class SessionContext(Protocol):
    def append_message(self, message: Message) -> None: ...
    def latest_message(self, session_id: str, role: str | None = None) -> Message | None: ...
    def next_stream_seq(self, request_id: str) -> int: ...
    def append_stream_delta(self, delta: StreamDelta) -> None: ...
    def stream_for_request(self, request_id: str) -> list[StreamDelta]: ...


class SharedStateContext(Protocol):
    def set_main_visible_state(self, state: MainVisibleState) -> None: ...
    def get_main_visible_state(self, session_id: str, request_id: str) -> MainVisibleState | None: ...
    def set_interaction_state(self, state: InteractionState) -> None: ...


class TaskContext(Protocol):
    def spawn_task(self, spec: TaskSpec) -> str: ...
    def stop_task(self, task_id: str) -> None: ...
    def cancel_task(self, task_id: str) -> None: ...
    def get_task_state(self, task_id: str) -> TaskState | None: ...
    def get_task_tail(self, task_id: str, limit: int = 100) -> str: ...


class AuditContext(Protocol):
    def review(self, request: AuditRequest) -> AuditResult: ...


@dataclass(slots=True)
class SignalContext:
    cancelled: bool = False
    paused: bool = False
    heartbeat_ms: int = 0

    def check_cancelled(self) -> bool:
        return self.cancelled

    def check_paused(self) -> bool:
        return self.paused

    def cancel(self) -> None:
        self.cancelled = True

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def heartbeat(self, now_ms: int) -> None:
        self.heartbeat_ms = now_ms
