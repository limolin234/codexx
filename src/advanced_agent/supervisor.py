from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from subprocess import Popen, TimeoutExpired
from typing import Sequence
from uuid import uuid4

from advanced_agent.audit import AuditAgent
from advanced_agent.codex_worker import CodexCommandSpec, CodexTaskHandle, CodexTaskWorker
from advanced_agent.interrupts import InterruptGate
from advanced_agent.models import AgentRole, AuditRequest, CommandPriority, ControlCommand, ReviewDecision, TaskSpec, TaskState
from advanced_agent.stores.audit_store import ControlStore
from advanced_agent.stores.task_store import TaskStore
from advanced_agent.time_service import TimeService


class WorkerState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True)
class WorkerSpec:
    name: str
    command: Sequence[str]
    role: str
    version: str = "0.1.0"
    permissions: list[str] = field(default_factory=list)
    cwd: str | None = None
    id: str = field(default_factory=lambda: f"worker_{uuid4().hex}")


@dataclass(slots=True)
class WorkerHandle:
    spec: WorkerSpec
    process: Popen[bytes]
    state: WorkerState = WorkerState.STARTING


class Supervisor:
    """Main-process control plane.

    It owns process handles and low-level control. Agents request graceful
    operations (`stop`, `pause`, `cancel`); raw terminate/kill is supervisor
    fallback only.
    """

    def __init__(
        self,
        time: TimeService | None = None,
        task_store: TaskStore | None = None,
        control_store: ControlStore | None = None,
        audit_agent: AuditAgent | None = None,
        interrupt_gate: InterruptGate | None = None,
        codex_worker: CodexTaskWorker | None = None,
    ) -> None:
        self.time = time or TimeService()
        self.task_store = task_store
        self.control_store = control_store
        self.audit_agent = audit_agent
        self.interrupt_gate = interrupt_gate
        self.codex_worker = codex_worker
        self.workers: dict[str, WorkerHandle] = {}
        self.task_workers: dict[str, str] = {}
        self.task_handles: dict[str, CodexTaskHandle] = {}
        self.task_waiters: dict[str, asyncio.Task[int]] = {}

    def start_worker(self, spec: WorkerSpec) -> WorkerHandle:
        process = Popen(
            list(spec.command),
            cwd=spec.cwd,
            stdin=-1,
            stdout=-1,
            stderr=-1,
        )
        handle = WorkerHandle(spec=spec, process=process)
        self.workers[spec.id] = handle
        return handle

    def stop_worker(self, worker_id: str, timeout: float = 5.0) -> None:
        """Gracefully terminate a worker, with kill as a private fallback."""
        handle = self.workers[worker_id]
        handle.state = WorkerState.STOPPING
        handle.process.terminate()
        try:
            handle.process.wait(timeout=timeout)
        except TimeoutExpired:
            handle.process.kill()
            handle.process.wait()
        handle.state = WorkerState.STOPPED

    def poll(self, worker_id: str) -> WorkerState:
        handle = self.workers[worker_id]
        code = handle.process.poll()
        if code is None:
            return handle.state
        handle.state = WorkerState.STOPPED if code == 0 else WorkerState.FAILED
        return handle.state

    def spawn_task(self, spec: TaskSpec) -> str:
        self._review_task_spawn(spec)
        if self.task_store is None:
            return spec.id
        task_id = self.task_store.create_task(spec, self.time.wall_ms())
        self.task_store.update_task_state(task_id, "queued", self.time.wall_ms(), stage="waiting", summary="Task accepted by supervisor.")
        return task_id

    async def spawn_task_async(
        self,
        spec: TaskSpec,
        *,
        start: bool = True,
        codex_command: Sequence[str] | None = None,
        codex_spec: CodexCommandSpec | None = None,
    ) -> str:
        """Create a task and optionally start its configured backend.

        The synchronous `spawn_task` remains a pure admission path so existing
        callers can create queued work without requiring an asyncio loop. This
        async method is the runtime path for actual task backend startup.
        """

        task_id = self.spawn_task(spec)
        if start:
            await self.start_task(task_id, command=codex_command, codex_spec=codex_spec)
        return task_id

    async def start_task(
        self,
        task_id: str,
        *,
        command: Sequence[str] | None = None,
        codex_spec: CodexCommandSpec | None = None,
    ) -> CodexTaskHandle:
        if self.task_store is None:
            raise RuntimeError("TaskStore is required to start task backends.")
        spec = self.task_store.get_task_spec(task_id)
        if spec is None:
            raise KeyError(task_id)
        if spec.backend != "codex-cli":
            raise ValueError(f"Unsupported task backend: {spec.backend}")
        if self.codex_worker is None:
            raise RuntimeError("CodexTaskWorker is not configured.")
        if task_id in self.task_handles:
            return self.task_handles[task_id]

        handle = await self.codex_worker.start(
            task_id,
            prompt=spec.goal,
            workdir=Path(spec.workdir),
            command=command,
            spec=codex_spec,
        )
        self.task_handles[task_id] = handle
        self.task_workers[task_id] = handle.process.id
        self.task_waiters[task_id] = asyncio.create_task(self._wait_task_backend(handle), name=f"task-wait-{task_id}")
        return handle

    async def _wait_task_backend(self, handle: CodexTaskHandle) -> int:
        assert self.codex_worker is not None
        try:
            return await self.codex_worker.wait(handle)
        finally:
            self.task_waiters.pop(handle.task_id, None)

    async def stop_task_backend(self, task_id: str, timeout_seconds: float = 5.0) -> int | None:
        handle = self.task_handles.get(task_id)
        if handle is None or self.codex_worker is None:
            return None
        code = await self.codex_worker.runner.stop(handle.process.id, timeout_seconds=timeout_seconds)
        waiter = self.task_waiters.get(task_id)
        if waiter is not None:
            await asyncio.gather(waiter, return_exceptions=True)
        return code

    def _review_task_spawn(self, spec: TaskSpec) -> None:
        if self.audit_agent is not None:
            req = AuditRequest(
                subject_type="task",
                subject_id=spec.id,
                action="spawn_task",
                payload={"goal": spec.goal, "workdir": spec.workdir, "backend": spec.backend},
                requested_by=AgentRole.MAIN,
                priority=CommandPriority.MAIN,
                created_at_ms=self.time.wall_ms(),
            )
            result = self.audit_agent.review(req)
            if result.decision in (ReviewDecision.REJECT, ReviewDecision.STOP):
                raise PermissionError(result.reason)

    def request_task_control(self, task_id: str, command: ControlCommand, source: AgentRole, emergency: bool = False) -> bool:
        if self.interrupt_gate is not None:
            decision = self.interrupt_gate.evaluate(scope=f"task:{task_id}", source=source, emergency=emergency)
            if not decision.allowed:
                return False
            priority = int(decision.priority)
        else:
            priority = int(CommandPriority.MAIN if source == AgentRole.MAIN else CommandPriority.USER)

        if command in (ControlCommand.TERMINATE, ControlCommand.KILL) and source != AgentRole.AUDIT:
            return False

        if self.control_store is not None:
            self.control_store.add_command("task", task_id, command.value, priority, source.value, self.time.wall_ms())
        if command in (ControlCommand.STOP, ControlCommand.CANCEL) and self.task_store is not None:
            self.task_store.update_task_state(task_id, command.value, self.time.wall_ms(), summary=f"{command.value} requested by {source.value}.")
        return True

    async def request_task_control_async(self, task_id: str, command: ControlCommand, source: AgentRole, emergency: bool = False) -> bool:
        accepted = self.request_task_control(task_id, command, source, emergency=emergency)
        if not accepted:
            return False
        if command in (ControlCommand.STOP, ControlCommand.CANCEL, ControlCommand.TERMINATE, ControlCommand.KILL):
            await self.stop_task_backend(task_id)
        return True

    def stop_task(self, task_id: str, source: AgentRole = AgentRole.MAIN) -> bool:
        return self.request_task_control(task_id, ControlCommand.STOP, source)

    def cancel_task(self, task_id: str, source: AgentRole = AgentRole.MAIN) -> bool:
        return self.request_task_control(task_id, ControlCommand.CANCEL, source)

    def get_task_state(self, task_id: str) -> TaskState | None:
        if self.task_store is None:
            return None
        return self.task_store.get_state(task_id)

    def get_task_tail(self, task_id: str, limit: int = 100) -> str:
        if self.task_store is None:
            return ""
        return self.task_store.get_tail(task_id, limit)
