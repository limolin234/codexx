from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from advanced_agent.memory_indexer import MemoryCandidate, MemoryIndexer, MemoryIndexResult
from advanced_agent.vectors import SQLiteVecStore


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    scope: str
    type: str
    summary: str
    content: str | None
    importance: float
    confidence: float
    source_ref: str | None
    created_at_ms: int
    updated_at_ms: int
    label_kind: str | None = None
    labels: dict[str, str] | None = None
    distance: float | None = None
    score: float | None = None
    why_hit: dict | None = None

    def to_dict(self, include_content: bool = True, content_max_chars: int = 2000) -> dict[str, Any]:
        data: dict[str, Any] = {
            "memory_id": self.memory_id,
            "scope": self.scope,
            "type": self.type,
            "summary": self.summary,
            "importance": self.importance,
            "confidence": self.confidence,
            "source_ref": self.source_ref,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
        }
        if self.label_kind is not None:
            data["label_kind"] = self.label_kind
        if self.labels:
            data["labels"] = self.labels
        if self.distance is not None:
            data["distance"] = self.distance
        if self.score is not None:
            data["score"] = self.score
        if self.why_hit:
            data["why_hit"] = self.why_hit
        if include_content:
            content = self.content or ""
            data["content"] = content[:content_max_chars]
            data["content_truncated"] = len(content) > content_max_chars
        return data


class MemoryService:
    """High-level durable memory API used by runtime tools and MCP.

    `MemoryIndexer` remains the only write path for aligned vector memory. This
    service adds hydration/listing semantics so tool callers can retrieve actual
    previous records, not just vector IDs.
    """

    def __init__(self, indexer: MemoryIndexer, vectors: SQLiteVecStore) -> None:
        self.indexer = indexer
        self.vectors = vectors

    def write(
        self,
        *,
        summary: str,
        content: str | None = None,
        scope: str = "project:advanced_agent",
        type: str = "note",
        source_type: str = "tool",
        source_id: str | None = None,
        importance: float = 0.5,
        confidence: float = 0.8,
        agent_role: str = "main",
    ) -> MemoryIndexResult:
        candidate = MemoryCandidate(
            scope=scope,
            type=type,
            summary=summary,
            content=content if content is not None else summary,
            source_type=source_type,
            source_id=source_id or summary[:80],
            importance=importance,
            confidence=confidence,
        )
        return self.indexer.index(candidate, agent_role=agent_role)

    def search(self, query: str, scope: str | None = None, top_k: int = 5, query_profile: str = "auto", facet_weights: dict[str, float] | None = None) -> list[MemoryRecord]:
        hits = self.vectors.hybrid_search(query=query, scope=scope, top_k=max(top_k * 4, top_k), query_profile=query_profile, facet_weights=facet_weights)
        records: list[MemoryRecord] = []
        seen_memory_ids: set[str] = set()
        for hit in hits:
            if hit.memory_id in seen_memory_ids:
                continue
            record = self.get(hit.memory_id)
            if record is None:
                continue
            seen_memory_ids.add(hit.memory_id)
            record.label_kind = hit.label_kind
            record.distance = hit.distance
            record.score = hit.score
            record.why_hit = hit.why_hit
            records.append(record)
            if len(records) >= top_k:
                break
        return records

    def recent(self, scope: str | None = None, limit: int = 20, type: str | None = None) -> list[MemoryRecord]:
        where = ["status='active'"]
        params: list[Any] = []
        if scope is not None:
            where.append("scope=?")
            params.append(scope)
        if type is not None:
            where.append("type=?")
            params.append(type)
        params.append(limit)
        rows = self.vectors.db.query_all(
            f"""SELECT * FROM memory_items
            WHERE {' AND '.join(where)}
            ORDER BY updated_at_ms DESC, created_at_ms DESC
            LIMIT ?""",
            tuple(params),
        )
        return [self._record_from_row(row) for row in rows]

    def get(self, memory_id: str) -> MemoryRecord | None:
        row = self.vectors.db.query_one("SELECT * FROM memory_items WHERE id=? AND status='active'", (memory_id,))
        if row is None:
            return None
        return self._record_from_row(row)

    def _record_from_row(self, row: Any) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["id"],
            scope=row["scope"],
            type=row["type"],
            summary=row["summary"],
            content=row["content"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            source_ref=row["source_ref"],
            created_at_ms=int(row["created_at_ms"]),
            updated_at_ms=int(row["updated_at_ms"]),
            labels=self._labels_for_memory(row["id"]),
        )

    def _labels_for_memory(self, memory_id: str) -> dict[str, str]:
        rows = self.vectors.db.query_all(
            "SELECT label_kind, label_text FROM memory_vectors WHERE memory_id=? ORDER BY created_at_ms",
            (memory_id,),
        )
        return {row["label_kind"]: row["label_text"] for row in rows if row["label_text"]}
