from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    INTERACTIVE = "interactive"
    MAIN = "main"
    AUDIT = "audit"
    MEMORY = "memory"
    TASK = "task"


class Authority(StrEnum):
    PROVISIONAL = "provisional"
    AUTHORITATIVE = "authoritative"


class CommandPriority(IntEnum):
    SYSTEM = 20
    INTERACTIVE = 40
    USER = 60
    MAIN = 80
    AUDIT = 100


class ControlCommand(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    CANCEL = "cancel"
    SNAPSHOT = "snapshot"
    TERMINATE = "terminate"
    KILL = "kill"


class ReviewDecision(StrEnum):
    ALLOW = "allow"
    WARN = "warn"
    REJECT = "reject"
    STOP = "stop"


@dataclass(slots=True)
class StreamDelta:
    session_id: str
    request_id: str
    seq: int
    writer: AgentRole
    authority: Authority
    text: str
    timestamp_ms: int
    supersedes_seq: int | None = None
    id: str = field(default_factory=lambda: new_id("delta"))


@dataclass(slots=True)
class Message:
    session_id: str
    role: str
    content: str
    request_id: str | None
    created_at_ms: int
    seq: int | None = None
    id: str = field(default_factory=lambda: new_id("msg"))


@dataclass(slots=True)
class MainVisibleState:
    session_id: str
    request_id: str
    status: str
    visible_summary: str
    updated_at_ms: int
    id: str = field(default_factory=lambda: new_id("mainstate"))


@dataclass(slots=True)
class InteractionState:
    session_id: str
    request_id: str
    status: str
    last_sent_seq: int
    updated_at_ms: int
    id: str = field(default_factory=lambda: new_id("intstate"))


@dataclass(slots=True)
class TaskSpec:
    goal: str
    workdir: str
    backend: str = "codex-cli"
    session_id: str | None = None
    priority: int = 0
    id: str = field(default_factory=lambda: new_id("task"))


@dataclass(slots=True)
class TaskState:
    task_id: str
    status: str
    stage: str | None
    latest_summary: str | None
    need_attention: bool
    can_stop: bool
    updated_at_ms: int


@dataclass(slots=True)
class AuditRequest:
    subject_type: str
    subject_id: str
    action: str
    payload: dict[str, Any]
    requested_by: AgentRole
    priority: CommandPriority
    created_at_ms: int
    id: str = field(default_factory=lambda: new_id("auditreq"))


@dataclass(slots=True)
class AuditResult:
    request_id: str
    decision: ReviewDecision
    reason: str
    priority: CommandPriority
    created_at_ms: int
    id: str = field(default_factory=lambda: new_id("audit"))
