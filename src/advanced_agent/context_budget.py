from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Character-budget approximation for context control.

    Token counting can replace this later. The policy is intentionally simple:
    keep live dialogue short, rely on vector memory for retrieval.
    """

    max_chars: int = 24_000
    compact_threshold_ratio: float = 0.5
    recent_ratio: float = 0.35
    retrieved_ratio: float = 0.15

    @property
    def compact_threshold_chars(self) -> int:
        return int(self.max_chars * self.compact_threshold_ratio)

    @property
    def recent_chars(self) -> int:
        return int(self.max_chars * self.recent_ratio)

    @property
    def retrieved_chars(self) -> int:
        return int(self.max_chars * self.retrieved_ratio)
