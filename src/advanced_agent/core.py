from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4


class AgentRole(StrEnum):
    FAST_BUFFER = "fast_buffer"
    MAIN = "main_agent"
    TASK = "task_agent"
    MEMORY = "memory_maintainer"
    TOOL = "tool_executor"


class Interrupt(StrEnum):
    CANCEL = "cancel"
    PAUSE = "pause"
    REDIRECT = "redirect"
    SNAPSHOT = "snapshot"


EventType = Literal[
    "user_message",
    "buffer_reply",
    "main_agent_decision",
    "task_started",
    "task_progress",
    "task_finished",
    "tool_call_requested",
    "tool_call_finished",
    "interrupt_requested",
    "memory_candidate",
    "memory_committed",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class AgentEvent:
    type: EventType
    payload: dict[str, Any]
    source: AgentRole | str
    id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class TaskSpec:
    goal: str
    context_slice: str
    allowed_tools: list[str] = field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    report_interval_seconds: int = 30
    id: str = field(default_factory=lambda: f"task_{uuid4().hex}")


@dataclass(slots=True)
class MemoryCandidate:
    type: Literal[
        "user_preference",
        "project_state",
        "environment_fact",
        "procedure",
        "decision",
        "warning",
    ]
    scope: str
    summary: str
    tags: list[str]
    source_events: list[str]
    confidence: float
    id: str = field(default_factory=lambda: f"mem_{uuid4().hex}")
