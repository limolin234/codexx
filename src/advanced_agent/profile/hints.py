from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from advanced_agent.auto_memory_design import AutoMemoryPolicy
from advanced_agent.memory_service import MemoryRecord, MemoryService
from advanced_agent.vectors import VectorHit


PROFILE_TYPES = ("user_trait", "preference", "workflow_habit")


@dataclass(slots=True)
class ProfileHint:
    profile_key: str
    hint: str
    updated_at_ms: int
    memory_id: str
    scope: str
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "hint": self.hint,
            "updated_at_ms": self.updated_at_ms,
        }


class ProfileHintSelector:
    """Select compact, query-relevant profile hints from vector memory.

    This is the synchronous read path for prompt injection. It must stay cheap:
    no LLM calls, no background maintenance, no debug payloads.
    """

    def __init__(self, memory: MemoryService, policy: AutoMemoryPolicy | None = None) -> None:
        self.memory = memory
        self.policy = policy or AutoMemoryPolicy()

    def select(self, *, query: str, scope: str, limit: int = 3, query_profile: str = "auto") -> list[ProfileHint]:
        if limit <= 0:
            return []
        scopes = self._scope_chain(scope)
        candidates: list[ProfileHint] = []
        seen_keys: set[str] = set()
        query = query.strip()

        if query:
            search_budget = max(limit * 4, limit)
            for depth, scope_name in enumerate(scopes):
                hits = self.memory.search(query, scope=scope_name, top_k=search_budget, query_profile=query_profile)
                for hit in hits:
                    hint = self._hint_from_hit(hit, scope_name, depth)
                    if hint is None:
                        continue
                    if hint.profile_key in seen_keys:
                        continue
                    seen_keys.add(hint.profile_key)
                    candidates.append(hint)
                    if len(candidates) >= search_budget:
                        break
                if len(candidates) >= search_budget:
                    break
            if not candidates:
                candidates.extend(self._recent_candidates(scopes=scopes, limit=search_budget, seen_keys=seen_keys))
        else:
            search_budget = max(limit * 4, limit)
            candidates.extend(self._recent_candidates(scopes=scopes, limit=search_budget, seen_keys=seen_keys))

        candidates.sort(key=lambda item: (item.score, item.updated_at_ms), reverse=True)
        return candidates[:limit]

    def _recent_candidates(self, *, scopes: list[str], limit: int, seen_keys: set[str]) -> list[ProfileHint]:
        candidates: list[ProfileHint] = []
        for depth, scope_name in enumerate(scopes):
            for record in self.memory.recent(scope=scope_name, limit=limit, type=None):
                hint = self._hint_from_record(record, scope_name, depth)
                if hint is None:
                    continue
                if hint.profile_key in seen_keys:
                    continue
                seen_keys.add(hint.profile_key)
                candidates.append(hint)
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break
        return candidates

    def _scope_chain(self, scope: str) -> list[str]:
        scope = scope.strip() or "project:advanced_agent"
        if scope == "global":
            return ["global"]
        chain: list[str] = [scope]
        if ":" in scope:
            head = scope.split(":", 1)[0]
            tail = scope.split(":", 1)[1]
            if tail and tail not in chain:
                chain.append(tail)
            if head and head not in chain:
                chain.append(head)
        if scope != "project" and "project" not in chain:
            chain.append("project")
        if "global" not in chain:
            chain.append("global")
        return chain

    def _hint_from_hit(self, hit: VectorHit, scope: str, depth: int) -> ProfileHint | None:
        record = self.memory.get(hit.memory_id)
        if record is None:
            return None
        return self._hint_from_record(record, scope, depth, score=hit.score or 0.0)

    def _hint_from_record(self, record: MemoryRecord, scope: str, depth: int, score: float | None = None) -> ProfileHint | None:
        if record.type not in PROFILE_TYPES:
            return None
        if not self.policy.can_inject(confidence=record.confidence, importance=record.importance, source=record.source_strength):
            return None
        if self._is_profile_evidence(record):
            return None
        summary = (record.summary or "").strip()
        if not summary:
            return None
        profile_key = self._profile_key(record)
        if not profile_key:
            return None
        base_score = score if score is not None else 0.0
        depth_boost = max(0.55, 1.0 - depth * 0.12)
        final_score = base_score * depth_boost + record.importance * 0.18 + record.confidence * 0.12 + self._recency_boost(record)
        return ProfileHint(
            profile_key=profile_key,
            hint=summary[:280],
            updated_at_ms=record.updated_at_ms,
            memory_id=record.memory_id,
            scope=scope,
            score=final_score,
        )

    def _profile_key(self, record: MemoryRecord) -> str:
        metadata = record.metadata or {}
        key = str(metadata.get("profile_key") or metadata.get("kind") or "").strip()
        if key:
            return key
        digest = hashlib.sha256(f"{record.type}:{record.summary}".encode("utf-8")).hexdigest()[:24]
        return f"{record.type}:{digest}"

    def _recency_boost(self, record: MemoryRecord) -> float:
        # Simple bounded decay. Newer records get a small bonus.
        age_ms = max(0, self.memory.vectors.time.wall_ms() - record.updated_at_ms)
        age_days = age_ms / 86_400_000.0
        return 0.1 / (1.0 + age_days / 30.0)

    def _is_profile_evidence(self, record: MemoryRecord) -> bool:
        metadata = record.metadata or {}
        kind = str(metadata.get("kind") or metadata.get("category") or "")
        if kind == "profile_evidence":
            return True
        return record.summary.strip().startswith("[profile_evidence]")
