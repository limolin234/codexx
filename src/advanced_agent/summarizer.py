from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SummaryResult:
    summary: str
    important_events: list[str]
    risks: list[str]


class TailSummarizer:
    """Cheap deterministic progress summarizer.

    This is a placeholder for a later small-model summarizer. It keeps bounded
    output and extracts obvious error/warning lines.
    """

    def summarize(self, tail: str, max_chars: int = 600) -> SummaryResult:
        lines = [line.strip() for line in tail.splitlines() if line.strip()]
        important = [line for line in lines if any(key in line.lower() for key in ("error", "failed", "warning", "critical"))]
        risks = [line for line in important if any(key in line.lower() for key in ("rm -rf", "permission", "denied", "critical"))]
        if not lines:
            summary = "No recent output."
        else:
            summary = "Recent output: " + " | ".join(lines[-5:])
        return SummaryResult(summary=summary[:max_chars], important_events=important[-5:], risks=risks[-5:])
