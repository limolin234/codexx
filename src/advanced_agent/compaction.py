from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.context_budget import ContextBudget
from advanced_agent.memory_indexer import MemoryCandidate, MemoryIndexer
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.time_service import TimeService
from advanced_agent.vectors import MemoryAlignment, SQLiteVecStore


@dataclass(slots=True)
class CompactionResult:
    compacted: bool
    compacted_messages: int = 0
    memory_id: str | None = None
    reason: str = ""


class ConversationCompactor:
    """Automatically compact over-budget dialogue into vector memory."""

    def __init__(self, sessions: SessionStore, vectors: SQLiteVecStore, alignment: MemoryAlignment, time: TimeService, budget: ContextBudget | None = None, memory_indexer: MemoryIndexer | None = None) -> None:
        self.sessions = sessions
        self.vectors = vectors
        self.alignment = alignment
        self.time = time
        self.budget = budget or ContextBudget()
        self.memory_indexer = memory_indexer

    def maybe_compact(self, session_id: str, scope: str = "project:advanced_agent") -> CompactionResult:
        total = self.sessions.uncompacted_char_count(session_id)
        if total <= self.budget.compact_threshold_chars:
            return CompactionResult(compacted=False, reason="under_threshold")
        messages = self.sessions.session_messages(session_id, include_compacted=False)
        if len(messages) <= 4:
            return CompactionResult(compacted=False, reason="too_few_messages")

        # Keep recent tail; compact older prefix until live text drops near recent budget.
        running = 0
        keep_from_index = len(messages)
        for i in range(len(messages) - 1, -1, -1):
            running += len(messages[i].content)
            if running > self.budget.recent_chars:
                keep_from_index = i + 1
                break
        compact_prefix = messages[:keep_from_index]
        if not compact_prefix:
            return CompactionResult(compacted=False, reason="nothing_to_compact")

        summary = self._summarize(session_id, compact_prefix)
        if self.memory_indexer is not None:
            indexed = self.memory_indexer.index(
                MemoryCandidate(
                    scope=scope,
                    type="session_summary",
                    summary=summary.splitlines()[0][:200] if summary else "Compacted session summary",
                    content=summary,
                    source_type="session_compaction",
                    source_id=f"{session_id}:{compact_prefix[-1].id}",
                    importance=0.6,
                    confidence=0.75,
                ),
                agent_role="main",
            )
            memory_id = indexed.memory_id
        else:
            labels = self.alignment.labels_for(summary, agent_role="main")
            memory_id = self.vectors.add_memory(scope=scope, type_="session_summary", summary=summary, content=summary, labels=labels, importance=0.6)
        count = self.sessions.mark_compacted_before(session_id, compact_prefix[-1].id)
        return CompactionResult(compacted=True, compacted_messages=count, memory_id=memory_id, reason="compacted_to_vector_memory")

    def _summarize(self, session_id: str, messages) -> str:
        dialogue_lines = []
        for line in self.sessions.session_context_lines(session_id, include_compacted=False):
            if len("\n".join(dialogue_lines)) > self.budget.retrieved_chars:
                break
            dialogue_lines.append(line)
        parts = []
        for msg in messages[-20:]:
            parts.append(f"{msg.role}: {msg.content[:300]}")
        text = "\n".join(dialogue_lines[-40:] or parts)
        return ("Compacted session summary:\n" + text)[: self.budget.retrieved_chars]
