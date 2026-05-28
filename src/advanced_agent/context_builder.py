from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.context_budget import ContextBudget
from advanced_agent.memory_service import MemoryRecord, MemoryService
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.vectors import SQLiteVecStore, VectorHit


@dataclass(slots=True)
class BuiltContext:
    recent_messages: list[str]
    retrieved_memories: list[VectorHit] | list[MemoryRecord]
    total_chars: int


class ContextBuilder:
    """Build bounded context from recent dialogue plus vector retrieval."""

    def __init__(self, sessions: SessionStore, vectors: SQLiteVecStore, budget: ContextBudget | None = None, memory: MemoryService | None = None) -> None:
        self.sessions = sessions
        self.vectors = vectors
        self.memory = memory
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
        hits = self.memory.search(query, scope=scope, top_k=5, query_profile=query_profile) if self.memory is not None else self.vectors.search(query, scope=scope, top_k=5, query_profile=query_profile)
        retrieved_total = 0
        bounded_hits = []
        for hit in hits:
            text = getattr(hit, "content", None) or hit.summary
            if retrieved_total + len(text) > self.budget.retrieved_chars:
                break
            bounded_hits.append(hit)
            retrieved_total += len(text)
        return BuiltContext(recent_messages=recent, retrieved_memories=bounded_hits, total_chars=total + retrieved_total)
