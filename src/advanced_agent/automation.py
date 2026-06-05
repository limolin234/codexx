from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.events import EventBus
from advanced_agent.hooks import HookKind, HookScheduler, HookSpec
from advanced_agent.compaction import ConversationCompactor
from advanced_agent.memory_indexer import MemoryCandidate, MemoryIndexer
from advanced_agent.memory_maintenance import MemoryMaintenanceWorker
from advanced_agent.semantic_worker import SemanticMaintenanceWorker
from advanced_agent.preferences import PreferenceWorker
from advanced_agent.stores.hook_store import HookStore
from advanced_agent.task_summary_worker import TaskSummaryWorker
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class AutomationResult:
    fired: int
    actions: list[str]


class AutomationEngine:
    """Persistent hook-driven maintenance engine.

    It is intentionally deterministic. Models may request hooks, but this
    engine owns the actual scheduling and triggering.
    """

    def __init__(self, hooks: HookStore, preferences: PreferenceWorker, events: EventBus, time: TimeService, compactor: ConversationCompactor | None = None, memory_indexer: MemoryIndexer | None = None, task_summary_worker: TaskSummaryWorker | None = None, memory_maintenance: MemoryMaintenanceWorker | None = None, semantic_maintenance: SemanticMaintenanceWorker | None = None) -> None:
        self.hooks = hooks
        self.preferences = preferences
        self.events = events
        self.time = time
        self.compactor = compactor
        self.memory_indexer = memory_indexer
        self.task_summary_worker = task_summary_worker
        self.memory_maintenance = memory_maintenance
        self.semantic_maintenance = semantic_maintenance
        self.backoff = HookScheduler(time)

    def ensure_session_maintenance(self, session_id: str, scope: str = "project:advanced_agent", idle_ms: int = 0) -> str:
        now = self.time.wall_ms()
        delay = self.backoff.sleep_backoff_for_idle(idle_ms)
        preference_hook_id = self.hooks.ensure_unique(
            HookKind.PREFERENCE_MAINTENANCE,
            target=f"session:{session_id}",
            now_ms=now,
            delay_ms=delay,
            payload={"session_id": session_id, "scope": scope},
        )
        self.hooks.ensure_unique(
            HookKind.COMPACT_MEMORY,
            target=f"session:{session_id}",
            now_ms=now,
            delay_ms=delay,
            payload={"session_id": session_id, "scope": scope},
        )
        self.hooks.ensure_unique(
            HookKind.MEMORY_MAINTENANCE,
            target=f"session:{session_id}",
            now_ms=now,
            delay_ms=delay,
            payload={"session_id": session_id, "scope": scope},
        )
        return preference_hook_id

    def tick(self, limit: int = 20, *, shutdown_flush: bool = False) -> AutomationResult:
        now = self.time.wall_ms()
        due = self.hooks.due(now, limit=limit)
        if shutdown_flush:
            due = [hook for hook in due if bool(hook.payload.get("flush_on_stop", False))]
        actions: list[str] = []
        for hook in due:
            action = self._handle_hook(hook)
            actions.append(action)
            self.hooks.mark_fired(hook, self.time.wall_ms())
            self.events.publish("hook.fired", "automation", {"hook_id": hook.id, "kind": str(hook.kind), "target": hook.target, "action": action})
        return AutomationResult(fired=len(due), actions=actions)

    def _handle_hook(self, hook: HookSpec) -> str:
        if hook.kind == HookKind.PREFERENCE_MAINTENANCE:
            session_id = hook.payload.get("session_id")
            scope = hook.payload.get("scope", "project:advanced_agent")
            if not session_id:
                return "preference_skipped_missing_session"
            profile_id = self.preferences.update_from_session(
                session_id,
                scope=scope,
                allow_major_write=bool(hook.payload.get("allow_major_write", False)),
            )
            return f"preference_updated:{profile_id}"
        if hook.kind == HookKind.CHECK_STATE:
            return "main_check_state_requested"
        if hook.kind == HookKind.CHECK_TASKS:
            if self.task_summary_worker is None:
                return "check_tasks_not_configured"
            result = self.task_summary_worker.summarize_active()
            return f"check_tasks:summarized:{result.summarized}/{result.scanned}"
        if hook.kind == HookKind.MEMORY_INDEX:
            if self.memory_indexer is None:
                return "memory_index_not_configured"
            text = hook.payload.get("text") or hook.payload.get("summary")
            if not text:
                return "memory_index_skipped_missing_text"
            candidate = MemoryCandidate(
                scope=hook.payload.get("scope", "project:advanced_agent"),
                type=hook.payload.get("type", "note"),
                summary=hook.payload.get("summary", text),
                content=text,
                source_type=hook.payload.get("source_type", "hook"),
                source_id=hook.id,
                importance=float(hook.payload.get("importance", 0.5)),
            )
            result = self.memory_indexer.index(candidate)
            return f"memory_index:{result.reason}:{result.memory_id}"
        if hook.kind == HookKind.COMPACT_MEMORY:
            if self.compactor is None:
                return "compact_memory_not_configured"
            session_id = hook.payload.get("session_id")
            scope = hook.payload.get("scope", "project:advanced_agent")
            if not session_id:
                return "compact_skipped_missing_session"
            result = self.compactor.maybe_compact(session_id, scope=scope)
            return f"compact:{result.reason}:{result.compacted_messages}"
        if hook.kind == HookKind.MEMORY_MAINTENANCE:
            if self.memory_maintenance is None:
                return "memory_maintenance_not_configured"
            result = self.memory_maintenance.run(
                session_id=hook.payload.get("session_id"),
                scope=hook.payload.get("scope", "project:advanced_agent"),
                allow_major_write=bool(hook.payload.get("allow_major_write", False)),
                raw_retention_ms=int(hook.payload.get("raw_retention_ms", 7 * 24 * 60 * 60 * 1000)),
                deleted_retention_ms=int(hook.payload.get("deleted_retention_ms", 30 * 24 * 60 * 60 * 1000)),
                archive_grace_ms=int(hook.payload.get("archive_grace_ms", 0)),
                limit=int(hook.payload.get("limit", 200)),
            )
            return f"memory_maintenance:profile={result.profile_id or '-'}:archived={result.archived_indexes}:purged={result.purged_deleted}:pruned={result.pruned_raw_rows}"
        if hook.kind == HookKind.SEMANTIC_MAINTENANCE:
            if self.semantic_maintenance is None:
                return "semantic_maintenance_not_configured"
            session_id = hook.payload.get("session_id")
            scope = hook.payload.get("scope", "project:advanced_agent")
            if not session_id:
                return "semantic_maintenance_skipped_missing_session"
            result = self.semantic_maintenance.run(
                session_id=session_id,
                scope=scope,
                reason=hook.payload.get("reason", "scheduled"),
                force=bool(hook.payload.get("force", False)),
                limit=int(hook.payload.get("limit", 10)),
            )
            return f"semantic_maintenance:created={result.tasks_created}:processed={result.tasks_processed}:summaries={result.summaries_created}:candidates={result.candidates_created}/{result.candidates_processed}:memories={result.memories_written}:reason={result.reason}"
        if hook.kind == HookKind.RAW_RETENTION:
            if self.memory_maintenance is None:
                return "raw_retention_not_configured"
            result = self.memory_maintenance.run(
                session_id=hook.payload.get("session_id"),
                scope=hook.payload.get("scope", "project:advanced_agent"),
                raw_retention_ms=int(hook.payload.get("raw_retention_ms", 7 * 24 * 60 * 60 * 1000)),
                limit=int(hook.payload.get("limit", 200)),
            )
            return f"raw_retention:pruned={result.pruned_raw_rows}"
        # External plugin hook. The core publishes the request and lets a
        # plugin-specific agent/worker decide what to read/write.
        if isinstance(hook.kind, str) and hook.kind.startswith("plugin."):
            self.events.publish("plugin.hook.requested", "automation", {"hook_id": hook.id, "kind": hook.kind, "target": hook.target, "payload": hook.payload})
            return f"plugin_hook_requested:{hook.kind}"
        return "ignored"
