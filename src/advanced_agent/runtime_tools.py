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
    "memory.archive_inactive_indexes": RuntimeToolRisk.SAFE_DB_WRITE,
    "memory.purge_deleted": RuntimeToolRisk.SAFE_DB_WRITE,
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
            self.app.memory.mark_used([hit.memory_id for hit in hits])
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
                source_strength=args.get("source_strength", "unknown"),
                stability=args.get("stability", "normal"),
                last_evidence_at_ms=args.get("last_evidence_at_ms"),
                supersedes_id=args.get("supersedes_id"),
                metadata=args.get("metadata"),
                agent_role=self.caller.value,
            )
            return {"ok": True, "memory_id": indexed.memory_id, "created": indexed.created, "reason": indexed.reason}
        if name == "memory.recent":
            records = self.app.memory.recent(scope=args.get("scope"), type=args.get("type"), limit=int(args.get("limit", 20)))
            self.app.memory.mark_used([record.memory_id for record in records])
            return {
                "ok": True,
                "order_by": ["updated_at_ms DESC", "created_at_ms DESC", "rowid DESC"],
                "instruction": "Results are already newest-first; do not manually sort for ordinary recent-activity recaps.",
                "memories": [record.to_dict(include_content=bool(args.get("include_content", True)), content_max_chars=int(args.get("content_max_chars", 2000))) for record in records],
            }
        if name == "memory.archive_inactive_indexes":
            archived = self.app.memory.archive_inactive_indexes(older_than_ms=args.get("older_than_ms"), limit=int(args.get("limit", 100)))
            return {"ok": True, "archived": archived}
        if name == "memory.purge_deleted":
            purged = self.app.memory.purge_deleted(older_than_ms=int(args["older_than_ms"]), limit=int(args.get("limit", 100)))
            return {"ok": True, "purged": purged}
        if name == "session.recent":
            session_id = args.get("session_id") or self.app.default_session()
            limit = int(args.get("limit", 20))
            return {"ok": True, "lines": self.app.sessions.session_context_lines(session_id, include_compacted=bool(args.get("include_compacted", False)))[-limit:]}
        if name == "session.raw_tail":
            session_id = args.get("session_id") or self.app.default_session()
            return {
                "ok": True,
                "session_id": session_id,
                "lines": self.app.raw_tail_lines(
                    session_id,
                    limit=int(args.get("limit", 80)),
                    max_chars=int(args.get("max_chars", 800)),
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
            view = str(args.get("view", "compact"))
            if view not in {"compact", "debug"}:
                raise ValueError("context.get view must be 'compact' or 'debug'")
            dedupe = str(args.get("dedupe", "on"))
            if dedupe not in {"on", "off"}:
                raise ValueError("context.get dedupe must be 'on' or 'off'")
            caller_session_id = str(args.get("caller_session_id") or args.get("codex_session_id") or "")
            recent_limit = int(args.get("recent_limit", 20))
            memory_top_k = int(args.get("memory_top_k", 5))
            query_profile = str(args.get("query_profile", "auto"))
            facet_weights = args.get("facet_weights")
            live_recent_limit = max(0, int(args.get("live_recent_limit", 12)))
            include_profile_arg = args.get("include_profile")
            include_profile = bool(include_profile_arg) if include_profile_arg is not None else mode == "supplement"
            profile_limit = int(args.get("profile_limit", 3))
            compact_result = self.app.compactor.maybe_compact(session_id, scope=scope)

            all_items = self.app.sessions.session_context_items(session_id, include_compacted=bool(args.get("include_compacted", False)))
            if mode == "supplement" and live_recent_limit:
                candidate_items = all_items[:-live_recent_limit] if len(all_items) > live_recent_limit else []
            else:
                candidate_items = all_items
            seen_context_ids = self.app.injection_ledger.seen_ids(session_id, caller_session_id, "context_line") if dedupe == "on" else set()
            selected_context_items = [item for item in candidate_items if str(item["id"]) not in seen_context_ids][-recent_limit:]
            lines = [item["line"] for item in selected_context_items]

            include_log_memories = bool(args.get("include_log_memories", False))
            exclude_types = set(args.get("exclude_memory_types", []) or [])
            if not include_log_memories:
                exclude_types.add("codex_interactive_log")
            exclude_types.update({"user_trait", "preference", "workflow_habit"})
            fetch_k = max(memory_top_k * 4, memory_top_k)
            raw_memories = self.app.memory.search(query, scope=scope, top_k=fetch_k, query_profile=query_profile, facet_weights=facet_weights) if query else self.app.memory.recent(scope=scope, limit=fetch_k)
            seen_memory_ids = self.app.injection_ledger.seen_ids(session_id, caller_session_id, "memory") if dedupe == "on" and query else set()
            memories = []
            for memory in raw_memories:
                if memory.type in exclude_types:
                    continue
                if memory.memory_id in seen_memory_ids:
                    continue
                memories.append(memory)
                if len(memories) >= memory_top_k:
                    break
            self.app.memory.mark_used([memory.memory_id for memory in memories])

            selected_profile_hints = self.app.profile_hints.select(query=query, scope=scope, limit=max(profile_limit * 4, profile_limit), query_profile=query_profile) if include_profile else []
            if dedupe == "on" and include_profile:
                seen_profile_keys = self.app.injection_ledger.seen_ids(session_id, caller_session_id, "profile_hint")
                selected_profile_hints = [hint for hint in selected_profile_hints if hint.profile_key not in seen_profile_keys]
            profile_hints = selected_profile_hints[:profile_limit]

            include_memory_content = bool(args.get("include_memory_content", mode == "full"))
            memory_content_max_chars = int(args.get("memory_content_max_chars", 1200 if mode == "full" else 600))
            compact_memories = [self._compact_memory_dict(hit, include_content=include_memory_content, content_max_chars=memory_content_max_chars) for hit in memories]
            memory_items = [hit.to_dict(include_content=include_memory_content, content_max_chars=memory_content_max_chars) for hit in memories] if view == "debug" else compact_memories

            if dedupe == "on":
                self.app.injection_ledger.mark_many(
                    session_id=session_id,
                    caller_session_id=caller_session_id,
                    item_kind="context_line",
                    items=[(str(item["id"]), str(item["created_at_ms"])) for item in selected_context_items],
                )
                if query:
                    self.app.injection_ledger.mark_many(
                        session_id=session_id,
                        caller_session_id=caller_session_id,
                        item_kind="memory",
                        items=[(memory.memory_id, str(memory.updated_at_ms)) for memory in memories],
                    )
                self.app.injection_ledger.mark_many(
                    session_id=session_id,
                    caller_session_id=caller_session_id,
                    item_kind="profile_hint",
                    items=[(hint.profile_key, str(hint.updated_at_ms)) for hint in profile_hints],
                )

            result = {
                "ok": True,
                "session_id": session_id,
                "mode": mode,
                "context_lines": lines,
                "profile_hints": [hint.to_dict() for hint in profile_hints],
                "memories": memory_items,
            }
            if view == "debug":
                result.update({
                    "maintenance": {"compacted": compact_result.compacted, "reason": compact_result.reason, "memory_id": compact_result.memory_id, "compacted_messages": compact_result.compacted_messages},
                    "live_recent_skipped": min(live_recent_limit, len(all_items)) if mode == "supplement" else 0,
                    "query_profile": query_profile,
                    "facet_weights": facet_weights or {},
                    "excluded_memory_types": sorted(exclude_types),
                    "recent": lines,
                    "supplemental_recent": lines,
                    "dedupe": {"enabled": dedupe == "on", "caller_session_id": caller_session_id},
                    "instruction": "Use this as supplemental prior context. In supplement mode, assume the external agent already sees the live recent dialogue; do not duplicate it unless you need mode='full'.",
                })
            elif compact_result.compacted:
                result["maintenance"] = {"compacted": True, "memory_id": compact_result.memory_id}
            return result
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



    def _compact_memory_dict(self, hit, *, include_content: bool, content_max_chars: int) -> dict[str, Any]:
        data: dict[str, Any] = {
            "memory_id": hit.memory_id,
            "type": hit.type,
            "summary": hit.summary,
            "updated_at_ms": hit.updated_at_ms,
            "importance": hit.importance,
            "confidence": hit.confidence,
        }
        if include_content:
            content = hit.content or ""
            data["content"] = content[:content_max_chars]
            data["content_truncated"] = len(content) > content_max_chars
        return data

def _result_dict(result: CapabilityResult) -> dict[str, Any]:
    return {"ok": result.ok, "data": result.data, "error": result.error, "request_id": result.request_id}


_TOOL_SPECS = tuple(
    RuntimeToolSpec(name, description, risk=runtime_tool_risk(name), auto_approve=runtime_tool_auto_approve(name))
    for name, description in (
        ("memory.search", "Search aligned vector memory."),
        ("memory.write", "Write an aligned memory candidate through MemoryIndexer."),
        ("memory.recent", "Read durable memory records sorted newest-first by updated_at_ms, created_at_ms, then rowid."),
        ("memory.archive_inactive_indexes", "Archive inactive/superseded/deleted memory indexes while retaining item tombstones."),
        ("memory.purge_deleted", "Physically purge deleted memory tombstones older than a cutoff."),
        ("context.get", "Get supplemental prior session context plus vector memory hits for a query."),
        ("session.recent", "Read recent user-visible session context lines."),
        ("session.raw_tail", "Read prior/overflow raw dialogue tail, mainly for early continuation from the last chat."),
        ("task.list", "List recent managed tasks."),
        ("task.state", "Read a managed task state."),
        ("task.tail", "Read recent task output."),
        ("project.info", "Read current cwd and inferred project root."),
        ("workdir.chdir", "Change the runtime working directory like built-in cd."),
        ("timer.schedule", "Schedule a wake hook; do not sleep inside the model."),
        ("event.wait", "Bounded wait for a runtime event."),
    )
)
