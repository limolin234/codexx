from __future__ import annotations

import json
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
    status: str = "active"
    source_strength: str = "unknown"
    stability: str = "normal"
    usage_count: int = 0
    last_used_at_ms: int | None = None
    last_evidence_at_ms: int | None = None
    supersedes_id: str | None = None
    superseded_by: str | None = None
    archived_at_ms: int | None = None
    metadata: dict[str, Any] | None = None
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
            "status": self.status,
            "source_strength": self.source_strength,
            "stability": self.stability,
            "usage_count": self.usage_count,
            "last_used_at_ms": self.last_used_at_ms,
            "last_evidence_at_ms": self.last_evidence_at_ms,
            "supersedes_id": self.supersedes_id,
            "superseded_by": self.superseded_by,
            "archived_at_ms": self.archived_at_ms,
        }
        if self.metadata:
            data["metadata"] = self.metadata
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
        source_strength: str = "unknown",
        stability: str = "normal",
        last_evidence_at_ms: int | None = None,
        supersedes_id: str | None = None,
        metadata: dict[str, Any] | None = None,
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
            source_strength=source_strength,
            stability=stability,
            last_evidence_at_ms=last_evidence_at_ms,
            supersedes_id=supersedes_id,
            metadata=metadata or {},
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
            ORDER BY updated_at_ms DESC, created_at_ms DESC, rowid DESC
            LIMIT ?""",
            tuple(params),
        )
        return [self._record_from_row(row) for row in rows]

    def get(self, memory_id: str, include_inactive: bool = False) -> MemoryRecord | None:
        if include_inactive:
            row = self.vectors.db.query_one("SELECT * FROM memory_items WHERE id=?", (memory_id,))
        else:
            row = self.vectors.db.query_one("SELECT * FROM memory_items WHERE id=? AND status='active'", (memory_id,))
        if row is None:
            return None
        return self._record_from_row(row)

    def deactivate(self, memory_id: str, *, status: str = "inactive", superseded_by: str | None = None, now_ms: int | None = None) -> bool:
        if status not in {"inactive", "superseded", "archived", "deleted"}:
            raise ValueError("memory status must be inactive, superseded, archived, or deleted")
        now = now_ms if now_ms is not None else self.indexer.time.wall_ms()
        cur = self.vectors.db.execute(
            "UPDATE memory_items SET status=?, superseded_by=COALESCE(?, superseded_by), updated_at_ms=? WHERE id=? AND status='active'",
            (status, superseded_by, now, memory_id),
        )
        return cur.rowcount > 0

    def mark_used(self, memory_ids: list[str], *, now_ms: int | None = None) -> int:
        if not memory_ids:
            return 0
        now = now_ms if now_ms is not None else self.indexer.time.wall_ms()
        placeholders = ",".join("?" for _ in memory_ids)
        cur = self.vectors.db.execute(
            f"UPDATE memory_items SET usage_count=usage_count+1, last_used_at_ms=?, updated_at_ms=? WHERE id IN ({placeholders}) AND status='active'",
            (now, now, *memory_ids),
        )
        return cur.rowcount

    def archive_inactive_indexes(self, *, older_than_ms: int | None = None, limit: int = 100) -> int:
        """Remove vector/FTS/facet rows for inactive memories, retaining item tombstones."""

        where = ["status IN ('inactive','superseded','deleted')", "archived_at_ms IS NULL"]
        params: list[Any] = []
        if older_than_ms is not None:
            where.append("updated_at_ms<?")
            params.append(older_than_ms)
        params.append(limit)
        rows = self.vectors.db.query_all(
            f"SELECT id FROM memory_items WHERE {' AND '.join(where)} ORDER BY updated_at_ms LIMIT ?",
            tuple(params),
        )
        now = self.indexer.time.wall_ms()
        archived = 0
        with self.vectors.db.transaction():
            for row in rows:
                memory_id = row["id"]
                self.vectors.delete_memory_indexes(memory_id)
                self.vectors.db.execute(
                    "UPDATE memory_items SET status='archived', archived_at_ms=?, updated_at_ms=? WHERE id=?",
                    (now, now, memory_id),
                )
                archived += 1
        return archived

    def purge_deleted(self, *, older_than_ms: int, limit: int = 100) -> int:
        rows = self.vectors.db.query_all(
            "SELECT id FROM memory_items WHERE status='deleted' AND updated_at_ms<? ORDER BY updated_at_ms LIMIT ?",
            (older_than_ms, limit),
        )
        purged = 0
        with self.vectors.db.transaction():
            for row in rows:
                memory_id = row["id"]
                self.vectors.delete_memory_indexes(memory_id)
                self.vectors.db.execute("DELETE FROM memory_items WHERE id=?", (memory_id,))
                purged += 1
        return purged

    def purge_type(self, type: str, *, limit: int = 100) -> int:
        """Physically remove memories of a deprecated type and their indexes."""

        rows = self.vectors.db.query_all(
            "SELECT id FROM memory_items WHERE type=? ORDER BY updated_at_ms LIMIT ?",
            (type, limit),
        )
        purged = 0
        with self.vectors.db.transaction():
            for row in rows:
                memory_id = row["id"]
                self.vectors.delete_memory_indexes(memory_id)
                self.vectors.db.execute("DELETE FROM memory_items WHERE id=?", (memory_id,))
                purged += 1
        return purged

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
            status=row["status"],
            source_strength=row["source_strength"] if "source_strength" in row.keys() else "unknown",
            stability=row["stability"] if "stability" in row.keys() else "normal",
            usage_count=int(row["usage_count"]) if "usage_count" in row.keys() else 0,
            last_used_at_ms=int(row["last_used_at_ms"]) if "last_used_at_ms" in row.keys() and row["last_used_at_ms"] is not None else None,
            last_evidence_at_ms=int(row["last_evidence_at_ms"]) if "last_evidence_at_ms" in row.keys() and row["last_evidence_at_ms"] is not None else None,
            supersedes_id=row["supersedes_id"] if "supersedes_id" in row.keys() else None,
            superseded_by=row["superseded_by"] if "superseded_by" in row.keys() else None,
            archived_at_ms=int(row["archived_at_ms"]) if "archived_at_ms" in row.keys() and row["archived_at_ms"] is not None else None,
            metadata=json.loads(row["metadata_json"]) if "metadata_json" in row.keys() and row["metadata_json"] else None,
            labels=self._labels_for_memory(row["id"]),
        )

    def _labels_for_memory(self, memory_id: str) -> dict[str, str]:
        rows = self.vectors.db.query_all(
            "SELECT label_kind, label_text FROM memory_vectors WHERE memory_id=? ORDER BY created_at_ms",
            (memory_id,),
        )
        return {row["label_kind"]: row["label_text"] for row in rows if row["label_text"]}
