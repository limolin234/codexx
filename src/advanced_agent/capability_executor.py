from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Sequence

from advanced_agent.hooks import HookKind, HookSpec
from advanced_agent.models import AgentRole, AuditRequest, CommandPriority, ControlCommand, ReviewDecision, TaskSpec, TaskState, new_id
from advanced_agent.stores.hook_store import HookStore
from advanced_agent.stores.task_store import TaskStore
from advanced_agent.supervisor import Supervisor
from advanced_agent.time_service import TimeService
from advanced_agent.vectors import SQLiteVecStore, VectorHit
from advanced_agent.workspace import WorkspaceState


DEFAULT_ROLE_CAPABILITIES: dict[AgentRole, set[str]] = {
    AgentRole.SUPERVISOR: {"*"},
    AgentRole.MAIN: {"task_state", "task_list", "task_tail", "task_history", "memory_search", "hook_schedule", "interrupt_request", "spawn_task", "project_info", "workdir_chdir"},
    AgentRole.AUDIT: {"task_state", "task_list", "task_tail", "task_history", "memory_search", "interrupt_request", "project_info", "workdir_chdir"},
    AgentRole.INTERACTIVE: {"task_state", "task_list", "task_tail", "project_info", "workdir_chdir"},
    AgentRole.MEMORY: {"memory_search", "hook_schedule"},
    AgentRole.TASK: {"task_state", "task_list", "task_tail", "task_history", "project_info", "workdir_chdir"},
}


@dataclass(slots=True)
class CapabilityRequest:
    """Provider-neutral internal representation of a capability call."""

    capability: str
    caller: AgentRole
    arguments: dict[str, Any] = field(default_factory=dict)
    external_call_id: str | None = None
    created_at_ms: int | None = None
    id: str = field(default_factory=lambda: new_id("capreq"))


@dataclass(slots=True)
class CapabilityResult:
    capability: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    request_id: str | None = None
    id: str = field(default_factory=lambda: new_id("capres"))


class CapabilityExecutor:
    """Execute internal capabilities through stable runtime boundaries.

    LLM provider tool calls should be adapted into CapabilityRequest first.
    This executor is deliberately small and high-level; it must not expose raw
    shell/file/process primitives to models.
    """

    def __init__(self, supervisor: Supervisor, tasks: TaskStore, vectors: SQLiteVecStore, hooks: HookStore, time: TimeService, workspace: WorkspaceState | None = None, role_capabilities: dict[AgentRole, set[str]] | None = None) -> None:
        self.supervisor = supervisor
        self.tasks = tasks
        self.vectors = vectors
        self.hooks = hooks
        self.time = time
        self.workspace = workspace or WorkspaceState()
        self.role_capabilities = role_capabilities or DEFAULT_ROLE_CAPABILITIES

    def execute(self, request: CapabilityRequest) -> CapabilityResult:
        try:
            return self._execute(request)
        except Exception as exc:
            return CapabilityResult(capability=request.capability, ok=False, error=str(exc), request_id=request.id)

    async def execute_async(self, request: CapabilityRequest) -> CapabilityResult:
        try:
            self._ensure_allowed(request)
            if request.capability == "spawn_task" and bool(request.arguments.get("start", False)):
                task_id = await self.supervisor.spawn_task_async(self._task_spec_from_args(request.arguments), start=True)
                return CapabilityResult(request.capability, True, {"task_id": task_id, "started": True}, request_id=request.id)
            if request.capability == "interrupt_request":
                self._audit(request, subject_type="task", subject_id=str(request.arguments.get("target_id", "")), action="interrupt_request")
                data = await self._interrupt_request_async(request)
                return CapabilityResult(request.capability, True, data, request_id=request.id)
            return self._execute(request)
        except Exception as exc:
            return CapabilityResult(capability=request.capability, ok=False, error=str(exc), request_id=request.id)

    def _execute(self, request: CapabilityRequest) -> CapabilityResult:
        self._ensure_allowed(request)
        name = request.capability
        args = request.arguments
        if name == "task_state":
            state = self.supervisor.get_task_state(str(args["task_id"]))
            return CapabilityResult(name, True, {"state": None if state is None else _task_state_dict(state)}, request_id=request.id)
        if name == "task_list":
            statuses = args.get("statuses")
            if statuses is not None and not isinstance(statuses, list):
                raise ValueError("statuses must be a list")
            return CapabilityResult(name, True, {"tasks": self.tasks.list_tasks(statuses=statuses, limit=int(args.get("limit", 20)))}, request_id=request.id)
        if name == "task_tail":
            task_id = str(args["task_id"])
            limit = int(args.get("limit", 100))
            return CapabilityResult(name, True, {"task_id": task_id, "tail": self.supervisor.get_task_tail(task_id, limit=limit)}, request_id=request.id)
        if name == "task_history":
            task_id = str(args["task_id"])
            return CapabilityResult(name, True, {"task_id": task_id, "history": self.tasks.history(task_id, output_limit=int(args.get("output_limit", 50)), event_limit=int(args.get("event_limit", 50)))}, request_id=request.id)
        if name == "memory_search":
            hits = self.vectors.search(query=str(args["query"]), scope=args.get("scope"), top_k=int(args.get("top_k", 5)))
            return CapabilityResult(name, True, {"hits": [_memory_hit_dict(hit) for hit in hits]}, request_id=request.id)
        if name == "project_info":
            info = self.workspace.info()
            return CapabilityResult(name, True, {"cwd": info.cwd, "project_root": info.project_root, "markers": info.markers}, request_id=request.id)
        if name == "workdir_chdir":
            info = self.workspace.chdir(str(args["path"]))
            return CapabilityResult(name, True, {"cwd": info.cwd, "project_root": info.project_root, "markers": info.markers}, request_id=request.id)
        if name == "hook_schedule":
            if str(args["kind"]).startswith("plugin."):
                self._audit(request, subject_type="hook", subject_id=str(args.get("target", "plugin")), action="hook_schedule")
            hook_id = self._schedule_hook(args)
            return CapabilityResult(name, True, {"hook_id": hook_id}, request_id=request.id)
        if name == "interrupt_request":
            self._audit(request, subject_type="task", subject_id=str(args.get("target_id", "")), action="interrupt_request")
            accepted = self._interrupt_request(request)
            return CapabilityResult(name, True, {"accepted": accepted}, request_id=request.id)
        if name == "spawn_task":
            if bool(args.get("start", False)):
                raise RuntimeError("spawn_task with start=true requires execute_async")
            task_id = self.supervisor.spawn_task(self._task_spec_from_args(args))
            return CapabilityResult(name, True, {"task_id": task_id, "started": False}, request_id=request.id)
        return CapabilityResult(name, False, error=f"unknown capability: {name}", request_id=request.id)

    def _ensure_allowed(self, request: CapabilityRequest) -> None:
        allowed = self.role_capabilities.get(request.caller, set())
        if "*" in allowed or request.capability in allowed:
            return
        raise PermissionError(f"{request.caller.value} is not allowed to call capability {request.capability}")

    def _audit(self, request: CapabilityRequest, subject_type: str, subject_id: str, action: str) -> None:
        if self.supervisor.audit_agent is None:
            return
        result = self.supervisor.audit_agent.review(
            AuditRequest(
                subject_type=subject_type,
                subject_id=subject_id,
                action=action,
                payload={"capability": request.capability, "arguments": request.arguments},
                requested_by=request.caller,
                priority=CommandPriority.MAIN if request.caller != AgentRole.AUDIT else CommandPriority.AUDIT,
                created_at_ms=self.time.wall_ms(),
            )
        )
        if result.decision in (ReviewDecision.REJECT, ReviewDecision.STOP):
            raise PermissionError(result.reason)

    def _task_spec_from_args(self, args: dict[str, Any]) -> TaskSpec:
        return TaskSpec(
            goal=str(args["goal"]),
            workdir=str(args["workdir"]),
            backend=str(args.get("backend", "codex-cli")),
            session_id=args.get("session_id"),
            priority=int(args.get("priority", 0)),
        )

    def _find_project_root(self, start: Path) -> Path:
        markers = ("pyproject.toml", ".git", "AGENT.md")
        current = start.resolve()
        for parent in (current, *current.parents):
            if any((parent / marker).exists() for marker in markers):
                return parent
        return current

    def _project_markers(self, root: Path) -> list[str]:
        return [marker for marker in ("pyproject.toml", ".git", "AGENT.md") if (root / marker).exists()]

    def _schedule_hook(self, args: dict[str, Any]) -> str:
        kind = str(args["kind"])
        target = str(args.get("target", "main"))
        delay_ms = int(args.get("delay_ms", 0))
        repeat_ms = args.get("repeat_ms")
        payload = args.get("payload") or {}
        now = self.time.wall_ms()
        if kind in {item.value for item in HookKind}:
            return self.hooks.schedule_in(HookKind(kind), target=target, now_ms=now, delay_ms=delay_ms, payload=payload, repeat_ms=repeat_ms)
        if kind.startswith("plugin."):
            hook = HookSpec(kind=kind, target=target, wake_at_ms=now + delay_ms, payload=payload, repeat_ms=repeat_ms)
            return self.hooks.schedule(hook, now)
        raise ValueError(f"unsupported hook kind: {kind}")

    def _interrupt_request(self, request: CapabilityRequest) -> bool:
        args = request.arguments
        target_type = str(args.get("target_type", "task"))
        if target_type != "task":
            raise ValueError(f"unsupported interrupt target_type: {target_type}")
        command = ControlCommand(str(args["command"]))
        return self.supervisor.request_task_control(str(args["target_id"]), command, request.caller, emergency=bool(args.get("emergency", False)))

    async def _interrupt_request_async(self, request: CapabilityRequest) -> dict[str, Any]:
        args = request.arguments
        target_type = str(args.get("target_type", "task"))
        if target_type != "task":
            raise ValueError(f"unsupported interrupt target_type: {target_type}")
        command = ControlCommand(str(args["command"]))
        accepted = await self.supervisor.request_task_control_async(str(args["target_id"]), command, request.caller, emergency=bool(args.get("emergency", False)))
        return {"accepted": accepted}


class OpenAIToolAdapter:
    """Boundary adapter between official tool calls and internal capabilities."""

    @staticmethod
    def tool_schemas(names: Sequence[str] | None = None) -> list[dict[str, Any]]:
        selected = list(names) if names is not None else list(_TOOL_SCHEMAS.keys())
        return [_TOOL_SCHEMAS[name] for name in selected if name in _TOOL_SCHEMAS]

    @staticmethod
    def request_from_tool_call(tool_call: dict[str, Any], caller: AgentRole, now_ms: int | None = None) -> CapabilityRequest:
        function = tool_call.get("function", {})
        name = function.get("name") or tool_call.get("name")
        raw_args = function.get("arguments", tool_call.get("arguments", {}))
        if isinstance(raw_args, str):
            arguments = json.loads(raw_args or "{}")
        elif isinstance(raw_args, dict):
            arguments = raw_args
        else:
            raise ValueError("tool call arguments must be JSON string or object")
        return CapabilityRequest(
            capability=str(name),
            caller=caller,
            arguments=arguments,
            external_call_id=tool_call.get("id"),
            created_at_ms=now_ms,
        )

    @staticmethod
    def result_to_tool_message(result: CapabilityResult, tool_call_id: str | None = None) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id or result.request_id or result.id,
            "content": json.dumps({"ok": result.ok, "data": result.data, "error": result.error}, ensure_ascii=False),
        }


def _task_state_dict(state: TaskState) -> dict[str, Any]:
    return {
        "task_id": state.task_id,
        "status": state.status,
        "stage": state.stage,
        "latest_summary": state.latest_summary,
        "need_attention": state.need_attention,
        "can_stop": state.can_stop,
        "updated_at_ms": state.updated_at_ms,
    }


def _memory_hit_dict(hit: VectorHit) -> dict[str, Any]:
    return {
        "memory_id": hit.memory_id,
        "scope": hit.scope,
        "type": hit.type,
        "summary": hit.summary,
        "label_kind": hit.label_kind,
        "distance": hit.distance,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "task_state": {
        "type": "function",
        "function": {
            "name": "task_state",
            "description": "Read current status and latest summary of a managed task.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False},
        },
    },
    "task_tail": {
        "type": "function",
        "function": {
            "name": "task_tail",
            "description": "Read recent stdout/stderr chunks of a managed task without interrupting it.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, "required": ["task_id"], "additionalProperties": False},
        },
    },
    "task_list": {
        "type": "function",
        "function": {
            "name": "task_list",
            "description": "List recent managed tasks when the task id is unknown.",
            "parameters": {"type": "object", "properties": {"statuses": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": [], "additionalProperties": False},
        },
    },
    "task_history": {
        "type": "function",
        "function": {
            "name": "task_history",
            "description": "Read task state, output chunks, events, and summaries.",
            "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}, "output_limit": {"type": "integer"}, "event_limit": {"type": "integer"}}, "required": ["task_id"], "additionalProperties": False},
        },
    },
    "memory_search": {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Search aligned vector memory by semantic query and optional scope.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "scope": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 20}, "query_profile": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        },
    },
    "project_info": {
        "type": "function",
        "function": {
            "name": "project_info",
            "description": "Read current runtime working directory and inferred project root. Use this for questions about where the project is located.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
    },
    "workdir_chdir": {
        "type": "function",
        "function": {
            "name": "workdir_chdir",
            "description": "Change the agent runtime working directory, like a built-in cd command. Use before project/file/task work in another directory.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
        },
    },
    "hook_schedule": {
        "type": "function",
        "function": {
            "name": "hook_schedule",
            "description": "Schedule a deterministic runtime hook/wakeup. This does not imply user-visible speech.",
            "parameters": {"type": "object", "properties": {"kind": {"type": "string"}, "target": {"type": "string"}, "delay_ms": {"type": "integer", "minimum": 0}, "repeat_ms": {"type": "integer", "minimum": 1000}, "payload": {"type": "object"}}, "required": ["kind"], "additionalProperties": False},
        },
    },
    "interrupt_request": {
        "type": "function",
        "function": {
            "name": "interrupt_request",
            "description": "Request orderly pause/resume/stop/cancel for a managed task. Runtime/audit owns final control.",
            "parameters": {"type": "object", "properties": {"target_type": {"type": "string", "enum": ["task"]}, "target_id": {"type": "string"}, "command": {"type": "string", "enum": ["pause", "resume", "stop", "cancel", "snapshot"]}, "emergency": {"type": "boolean"}}, "required": ["target_id", "command"], "additionalProperties": False},
        },
    },
    "spawn_task": {
        "type": "function",
        "function": {
            "name": "spawn_task",
            "description": "Create a bounded task, usually backed by Codex CLI for code/file/project work.",
            "parameters": {"type": "object", "properties": {"goal": {"type": "string"}, "workdir": {"type": "string"}, "backend": {"type": "string", "enum": ["codex-cli"]}, "session_id": {"type": "string"}, "priority": {"type": "integer"}, "start": {"type": "boolean"}}, "required": ["goal", "workdir"], "additionalProperties": False},
        },
    },
}
