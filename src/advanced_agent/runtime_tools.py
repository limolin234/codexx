from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from advanced_agent.capability_executor import CapabilityRequest, CapabilityResult
from advanced_agent.hooks import HookKind
from advanced_agent.models import AgentRole
from advanced_agent.runtime.app import RuntimeApp


class RuntimeToolRisk(StrEnum):
    SAFE_READ = "safe_read"
    SAFE_DB_WRITE = "safe_db_write"
    SAFE_STATE_WRITE = "safe_state_write"
    UNSAFE = "unsafe"


SAFE_MCP_AUTO_APPROVE_TOOLS: dict[str, RuntimeToolRisk] = {
    "memory.search": RuntimeToolRisk.SAFE_READ,
    "memory.recent": RuntimeToolRisk.SAFE_READ,
    "context.get": RuntimeToolRisk.SAFE_READ,
    "session.recent": RuntimeToolRisk.SAFE_READ,
    "session.raw_tail": RuntimeToolRisk.SAFE_READ,
    "task.list": RuntimeToolRisk.SAFE_READ,
    "task.state": RuntimeToolRisk.SAFE_READ,
    "task.tail": RuntimeToolRisk.SAFE_READ,
    "project.info": RuntimeToolRisk.SAFE_READ,
    "event.wait": RuntimeToolRisk.SAFE_READ,
    "memory.write": RuntimeToolRisk.SAFE_DB_WRITE,
    "workdir.chdir": RuntimeToolRisk.SAFE_STATE_WRITE,
    "timer.schedule": RuntimeToolRisk.SAFE_STATE_WRITE,
}


def runtime_tool_risk(name: str) -> RuntimeToolRisk:
    return SAFE_MCP_AUTO_APPROVE_TOOLS.get(name, RuntimeToolRisk.UNSAFE)


def runtime_tool_auto_approve(name: str) -> bool:
    return runtime_tool_risk(name) is not RuntimeToolRisk.UNSAFE


@dataclass(frozen=True, slots=True)
class RuntimeToolSpec:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    risk: RuntimeToolRisk = RuntimeToolRisk.SAFE_READ
    auto_approve: bool = True


class RuntimeToolBridge:
    """Project-level tool bridge for future MCP exposure.

    This is intentionally not tied to one MCP Python package. MCP wrappers,
    Codex adapters, or tests can all call this bridge and get the same runtime
    behavior.
    """

    def __init__(self, app: RuntimeApp, caller: AgentRole = AgentRole.MAIN) -> None:
        self.app = app
        self.caller = caller

    def specs(self) -> list[RuntimeToolSpec]:
        return list(_TOOL_SPECS)

    def tool_policy(self, name: str) -> dict[str, Any]:
        risk = runtime_tool_risk(name)
        return {"name": name, "risk": risk.value, "auto_approve": risk is not RuntimeToolRisk.UNSAFE}

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        if name == "memory.search":
            hits = self.app.memory.search(
                query=str(args["query"]),
                scope=args.get("scope"),
                top_k=int(args.get("top_k", 5)),
                query_profile=str(args.get("query_profile", "auto")),
                facet_weights=args.get("facet_weights"),
            )
            include_content = bool(args.get("include_content", True))
            content_max_chars = int(args.get("content_max_chars", 2000))
            hit_dicts = [hit.to_dict(include_content=include_content, content_max_chars=content_max_chars) for hit in hits]
            return {"ok": True, "hits": hit_dicts, "data": {"hits": hit_dicts}}
        if name == "memory.write":
            indexed = self.app.memory.write(
                scope=args.get("scope", "project:advanced_agent"),
                type=args.get("type", "note"),
                summary=args["summary"],
                content=args.get("content", args["summary"]),
                source_type=args.get("source_type", "tool"),
                source_id=args.get("source_id", args["summary"][:80]),
                importance=float(args.get("importance", 0.5)),
                confidence=float(args.get("confidence", 0.8)),
                agent_role=self.caller.value,
            )
            return {"ok": True, "memory_id": indexed.memory_id, "created": indexed.created, "reason": indexed.reason}
        if name == "memory.recent":
            records = self.app.memory.recent(scope=args.get("scope"), type=args.get("type"), limit=int(args.get("limit", 20)))
            return {"ok": True, "memories": [record.to_dict(include_content=bool(args.get("include_content", True)), content_max_chars=int(args.get("content_max_chars", 2000))) for record in records]}
        if name == "session.recent":
            session_id = args.get("session_id") or self.app.default_session()
            limit = int(args.get("limit", 20))
            return {"ok": True, "lines": self.app.sessions.session_context_lines(session_id, include_compacted=bool(args.get("include_compacted", False)))[-limit:]}
        if name == "session.raw_tail":
            session_id = args.get("session_id") or self.app.default_session()
            return {
                "ok": True,
                "session_id": session_id,
                "lines": self.app.sessions.raw_tail_lines(
                    session_id,
                    limit=int(args.get("limit", 80)),
                    max_chars=int(args.get("max_chars", 800)),
                    include_compacted=bool(args.get("include_compacted", True)),
                ),
                "instruction": "Raw tail is a bounded ring-buffer-like dialogue tail for inspection only; use vector memory for durable semantics.",
            }
        if name == "context.get":
            session_id = args.get("session_id") or self.app.default_session()
            query = args.get("query", "")
            scope = args.get("scope", "project:advanced_agent")
            mode = str(args.get("mode", "supplement"))
            if mode not in {"supplement", "full"}:
                raise ValueError("context.get mode must be 'supplement' or 'full'")
            recent_limit = int(args.get("recent_limit", 20))
            memory_top_k = int(args.get("memory_top_k", 5))
            query_profile = str(args.get("query_profile", "auto"))
            facet_weights = args.get("facet_weights")
            live_recent_limit = max(0, int(args.get("live_recent_limit", 12)))
            compact_result = self.app.compactor.maybe_compact(session_id, scope=scope)
            all_lines = self.app.sessions.session_context_lines(session_id, include_compacted=bool(args.get("include_compacted", False)))
            if mode == "supplement" and live_recent_limit:
                candidate_lines = all_lines[:-live_recent_limit] if len(all_lines) > live_recent_limit else []
            else:
                candidate_lines = all_lines
            lines = candidate_lines[-recent_limit:]
            include_log_memories = bool(args.get("include_log_memories", False))
            exclude_types = set(args.get("exclude_memory_types", []) or [])
            if not include_log_memories:
                exclude_types.add("codex_interactive_log")
            fetch_k = max(memory_top_k * 4, memory_top_k)
            raw_memories = self.app.memory.search(query, scope=scope, top_k=fetch_k, query_profile=query_profile, facet_weights=facet_weights) if query else self.app.memory.recent(scope=scope, limit=fetch_k)
            memories = [memory for memory in raw_memories if memory.type not in exclude_types][:memory_top_k]
            include_memory_content = bool(args.get("include_memory_content", mode == "full"))
            memory_content_max_chars = int(args.get("memory_content_max_chars", 1200 if mode == "full" else 600))
            return {
                "ok": True,
                "session_id": session_id,
                "mode": mode,
                "maintenance": {"compacted": compact_result.compacted, "reason": compact_result.reason, "memory_id": compact_result.memory_id, "compacted_messages": compact_result.compacted_messages},
                "live_recent_skipped": min(live_recent_limit, len(all_lines)) if mode == "supplement" else 0,
                "query_profile": query_profile,
                "facet_weights": facet_weights or {},
                "excluded_memory_types": sorted(exclude_types),
                "recent": lines,
                "supplemental_recent": lines,
                "memories": [
                    hit.to_dict(include_content=include_memory_content, content_max_chars=memory_content_max_chars)
                    for hit in memories
                ],
                "instruction": "Use this as supplemental prior context. In supplement mode, assume the external agent already sees the live recent dialogue; do not duplicate it unless you need mode='full'.",
            }
        if name == "task.list":
            result = self.app.capability_executor.execute(CapabilityRequest("task_list", self.caller, args))
            return _result_dict(result)
        if name == "task.state":
            result = self.app.capability_executor.execute(CapabilityRequest("task_state", self.caller, {"task_id": args["task_id"]}))
            return _result_dict(result)
        if name == "task.tail":
            result = self.app.capability_executor.execute(CapabilityRequest("task_tail", self.caller, args))
            return _result_dict(result)
        if name == "project.info":
            result = self.app.capability_executor.execute(CapabilityRequest("project_info", self.caller, {}))
            return _result_dict(result)
        if name == "workdir.chdir":
            result = self.app.capability_executor.execute(CapabilityRequest("workdir_chdir", self.caller, {"path": args["path"]}))
            return _result_dict(result)
        if name == "timer.schedule":
            delay_ms = int(args["delay_ms"])
            hook_id = self.app.hooks.schedule_in(
                HookKind.WAKE,
                target=args.get("target", "main"),
                now_ms=self.app.time.wall_ms(),
                delay_ms=delay_ms,
                payload={"reason": args.get("reason", "timer"), **dict(args.get("payload", {}))},
            )
            return {"ok": True, "hook_id": hook_id, "wake_after_ms": delay_ms}
        if name == "event.wait":
            event_type = args.get("type")
            timeout_ms = min(int(args.get("timeout_ms", 0)), 30_000)
            deadline = time.monotonic() + timeout_ms / 1000.0
            while True:
                events = self.app.events.store.recent(int(args.get("limit", 50)))
                for event in reversed(events):
                    if event_type is None or event.type == event_type:
                        return {"ok": True, "event": {"id": event.id, "type": event.type, "source": event.source, "payload": event.payload, "created_at_ms": event.created_at_ms}}
                if timeout_ms <= 0 or time.monotonic() >= deadline:
                    return {"ok": True, "event": None, "timeout": True}
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        raise KeyError(f"unknown runtime tool: {name}")


def _result_dict(result: CapabilityResult) -> dict[str, Any]:
    return {"ok": result.ok, "data": result.data, "error": result.error, "request_id": result.request_id}


_TOOL_SPECS = tuple(
    RuntimeToolSpec(name, description, risk=runtime_tool_risk(name), auto_approve=runtime_tool_auto_approve(name))
    for name, description in (
        ("memory.search", "Search aligned vector memory."),
        ("memory.write", "Write an aligned memory candidate through MemoryIndexer."),
        ("memory.recent", "Read recent durable memory records, useful when the query is vague."),
        ("context.get", "Get fused recent session context plus vector memory hits for a query."),
        ("session.recent", "Read recent user-visible session context lines."),
        ("session.raw_tail", "Read bounded raw dialogue tail as a ring-buffer-like overflow guard."),
        ("task.list", "List recent managed tasks."),
        ("task.state", "Read a managed task state."),
        ("task.tail", "Read recent task output."),
        ("project.info", "Read current cwd and inferred project root."),
        ("workdir.chdir", "Change the runtime working directory like built-in cd."),
        ("timer.schedule", "Schedule a wake hook; do not sleep inside the model."),
        ("event.wait", "Bounded wait for a runtime event."),
    )
)
