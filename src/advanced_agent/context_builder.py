from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.context_budget import ContextBudget
from advanced_agent.memory_service import MemoryRecord, MemoryService
from advanced_agent.profile.hints import ProfileHint, ProfileHintSelector
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.vectors import SQLiteVecStore, VectorHit


@dataclass(slots=True)
class BuiltContext:
    recent_messages: list[str]
    retrieved_memories: list[VectorHit] | list[MemoryRecord]
    profile_hints: list[ProfileHint]
    total_chars: int


class ContextBuilder:
    """Build bounded context from recent dialogue plus vector retrieval."""

    def __init__(self, sessions: SessionStore, vectors: SQLiteVecStore, budget: ContextBudget | None = None, memory: MemoryService | None = None, profile_selector: ProfileHintSelector | None = None) -> None:
        self.sessions = sessions
        self.vectors = vectors
        self.memory = memory
        self.profile_selector = profile_selector
        self.budget = budget or ContextBudget()

    def build_for_main(self, session_id: str, query: str, scope: str = "project:advanced_agent", query_profile: str = "auto") -> BuiltContext:
        lines = self.sessions.session_context_lines(session_id, include_compacted=False)
        recent: list[str] = []
        total = 0
        for line in reversed(lines):
            if total + len(line) > self.budget.recent_chars:
                break
            recent.append(line)
            total += len(line)
        recent.reverse()
        # Overfetch so separately-injected profile traits do not crowd out
        # ordinary task memories when profile records rank highly for a query.
        hits = self.memory.search(query, scope=scope, top_k=12, query_profile=query_profile) if self.memory is not None else self.vectors.search(query, scope=scope, top_k=12, query_profile=query_profile)
        retrieved_total = 0
        bounded_hits = []
        for hit in hits:
            if getattr(hit, "type", None) in {"user_trait", "preference", "workflow_habit"}:
                continue
            text = getattr(hit, "content", None) or hit.summary
            if retrieved_total + len(text) > self.budget.retrieved_chars:
                break
            bounded_hits.append(hit)
            retrieved_total += len(text)
            if len(bounded_hits) >= 5:
                break
        if self.memory is not None:
            self.memory.mark_used([hit.memory_id for hit in bounded_hits])
        profile_hints = self.profile_selector.select(query=query, scope=scope, limit=3, query_profile=query_profile) if self.profile_selector is not None else []
        return BuiltContext(recent_messages=recent, retrieved_memories=bounded_hits, profile_hints=profile_hints, total_chars=total + retrieved_total)
