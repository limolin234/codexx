from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MemoryEvidenceSource(StrEnum):
    EXPLICIT_USER = "explicit_user"
    USER_CORRECTION = "user_correction"
    USER_BEHAVIOR = "user_behavior"
    TOOL_VERIFIED = "tool_verified"
    MODEL_SUMMARY = "model_summary"
    WRAPPER_INFERENCE = "wrapper_inference"
    ASSISTANT_OUTPUT = "assistant_output"


class MemoryCandidateAction(StrEnum):
    IGNORE = "ignore"
    CANDIDATE = "candidate"
    ESCALATE = "escalate"
    ADD = "add"
    UPDATE = "update"
    WEAKEN = "weaken"
    SUPERSEDE = "supersede"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class AutoMemoryPolicy:
    """Policy constants for wrapper-side automatic memory maintenance.

    The wrapper should not perform keyword-based semantic extraction. It records
    events, runs cheap observers for low-risk candidate generation, and lets a
    larger memory model approve durable writes/profile updates when confidence is
    low or the impact is high.
    """

    store_threshold: float = 0.55
    inject_threshold: float = 0.80
    high_impact_importance: float = 0.75
    cheap_confident_threshold: float = 0.82
    big_model_threshold: float = 0.65
    global_overlay_chars: int = 800
    workstream_overlay_chars: int = 800
    query_trait_limit: int = 3
    interrupt_exit_sync_timeout_ms: int = 300

    def should_escalate(self, *, confidence: float, importance: float, conflict: bool = False) -> bool:
        return conflict or confidence < self.big_model_threshold or importance >= self.high_impact_importance

    def can_store_candidate(self, *, confidence: float, source: str) -> bool:
        if source == MemoryEvidenceSource.ASSISTANT_OUTPUT:
            return False
        return confidence >= self.store_threshold

    def can_inject(self, *, confidence: float, importance: float, source: str) -> bool:
        if source in {MemoryEvidenceSource.ASSISTANT_OUTPUT, MemoryEvidenceSource.WRAPPER_INFERENCE}:
            return False
        return confidence >= self.inject_threshold and importance >= 0.6


@dataclass(slots=True)
class ProfileDiffPatch:
    action: MemoryCandidateAction
    summary: str = ""
    target_memory_id: str | None = None
    confidence: float = 0.0
    importance: float = 0.0
    stability: str = "normal"
    source_strength: str = MemoryEvidenceSource.WRAPPER_INFERENCE
    evidence: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


PROFILE_DIFF_PROMPT_CONTRACT = """
Maintain user profile as a diff against existing traits, not append-only notes.

Inputs:
- recent user-originated evidence and verified tool outcomes
- current active profile traits / relevant memories
- source metadata for each evidence item

Rules:
- Do not use assistant output as evidence for user traits.
- Do not keyword-match; decide semantically.
- Prefer no_change/strengthen/update existing traits over adding duplicates.
- Add or update only when there is a material difference from current traits.
- Low-confidence or high-impact changes must return action=escalate.
- Wrapper-inferred traits may become candidates but must not be injected until
  confirmed by explicit user evidence, user correction, or verified tool outcome.
- Preserve evidence and source_strength for cleanup and future conflict review.

Output JSON fields:
action, target_memory_id, summary, difference, evidence, confidence,
importance, stability, source_strength, reason, metadata.
""".strip()
