from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from advanced_agent.time_service import TimeService
from advanced_agent.vectors import MemoryAlignment, SQLiteVecStore
from advanced_agent.memory_alignment import MemoryAligner
from advanced_agent.memory_facets import normalize_facets


@dataclass(slots=True)
class MemoryCandidate:
    scope: str
    type: str
    summary: str
    content: str
    source_type: str
    source_id: str
    importance: float = 0.5
    confidence: float = 0.8
    facets: dict[str, str] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    source_strength: str = "unknown"
    stability: str = "normal"
    last_evidence_at_ms: int | None = None
    supersedes_id: str | None = None

    @property
    def source_ref(self) -> str:
        digest = hashlib.sha256(f"{self.source_type}:{self.source_id}:{self.content}".encode("utf-8")).hexdigest()
        return f"{self.source_type}:{self.source_id}:{digest}"


@dataclass(slots=True)
class MemoryIndexResult:
    memory_id: str
    created: bool
    reason: str


class MemoryIndexer:
    """Unified memory indexing pipeline.

    This is the single path for durable vector-indexed memory writes.
    """

    def __init__(self, vectors: SQLiteVecStore, alignment: MemoryAligner, time: TimeService) -> None:
        self.vectors = vectors
        self.alignment = alignment
        self.time = time

    def index(self, candidate: MemoryCandidate, agent_role: str = "main") -> MemoryIndexResult:
        existing = self.vectors.db.query_one(
            "SELECT id FROM memory_items WHERE source_ref=? AND status='active'",
            (candidate.source_ref,),
        )
        if existing:
            return MemoryIndexResult(memory_id=existing["id"], created=False, reason="duplicate_source_ref")
        text = candidate.summary + "\n" + candidate.content
        aligned = self.alignment.labels_for(text, agent_role=agent_role)
        labels = normalize_facets(
            {**aligned, **candidate.facets},
            summary=candidate.summary,
            content=candidate.content,
            type_=candidate.type,
            metadata={**candidate.metadata, "scope": candidate.scope, "created_at_ms": self.time.wall_ms()},
        )
        memory_id = self.vectors.add_memory(
            scope=candidate.scope,
            type_=candidate.type,
            summary=candidate.summary,
            labels=labels,
            content=candidate.content,
            importance=candidate.importance,
            confidence=candidate.confidence,
            source_ref=candidate.source_ref,
            source_strength=candidate.source_strength,
            stability=candidate.stability,
            last_evidence_at_ms=candidate.last_evidence_at_ms,
            supersedes_id=candidate.supersedes_id,
            metadata=candidate.metadata,
        )
        return MemoryIndexResult(memory_id=memory_id, created=True, reason="indexed")
