from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.auto_memory_design import AutoMemoryPolicy, MemoryEvidenceSource
from advanced_agent.memory_service import MemoryService
from advanced_agent.preferences import PreferenceWorker
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class MemoryMaintenanceResult:
    profile_id: str | None = None
    archived_indexes: int = 0
    purged_deleted: int = 0
    purged_raw_log_memories: int = 0
    pruned_raw_rows: int = 0


class MemoryMaintenanceWorker:
    """Deterministic background maintenance for wrapper-managed memory.

    This is the low-latency plumbing for automatic memory/profile maintenance.
    It intentionally does not perform keyword-based semantic extraction. Model
    adjudication can be plugged in later through pending candidates; this worker
    keeps profile overlays fresh, archives inactive indexes, purges old deleted
    tombstones, and prunes compacted raw rows after summaries exist.
    """

    def __init__(
        self,
        sessions: SessionStore,
        memory: MemoryService,
        preferences: PreferenceWorker,
        time: TimeService,
        policy: AutoMemoryPolicy | None = None,
    ) -> None:
        self.sessions = sessions
        self.memory = memory
        self.preferences = preferences
        self.time = time
        self.policy = policy or AutoMemoryPolicy()

    def run(
        self,
        *,
        session_id: str | None = None,
        scope: str = "project:advanced_agent",
        raw_retention_ms: int = 7 * 24 * 60 * 60 * 1000,
        deleted_retention_ms: int = 30 * 24 * 60 * 60 * 1000,
        archive_grace_ms: int = 0,
        limit: int = 200,
    ) -> MemoryMaintenanceResult:
        now = self.time.wall_ms()
        result = MemoryMaintenanceResult()
        if session_id:
            result.profile_id = self.preferences.update_from_session(session_id, scope=scope)
            result.pruned_raw_rows = self.sessions.prune_compacted_before_ms(
                session_id,
                cutoff_ms=now - raw_retention_ms,
                limit=limit,
            )
        result.purged_raw_log_memories = self.memory.purge_type("codex_interactive_log", limit=limit)
        result.archived_indexes = self.memory.archive_inactive_indexes(
            older_than_ms=now - archive_grace_ms if archive_grace_ms > 0 else None,
            limit=limit,
        )
        result.purged_deleted = self.memory.purge_deleted(
            older_than_ms=now - deleted_retention_ms,
            limit=limit,
        )
        return result

    def injectable_trait_filter(self, *, confidence: float, importance: float, source_strength: str) -> bool:
        return self.policy.can_inject(confidence=confidence, importance=importance, source=source_strength)

    def can_promote_wrapper_candidate(self, *, confidence: float, importance: float) -> bool:
        return self.policy.can_store_candidate(confidence=confidence, source=MemoryEvidenceSource.WRAPPER_INFERENCE) and not self.policy.should_escalate(confidence=confidence, importance=importance)
