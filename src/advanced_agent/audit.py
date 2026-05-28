from __future__ import annotations

from advanced_agent.models import AuditRequest, AuditResult, CommandPriority, ReviewDecision
from advanced_agent.stores.audit_store import AuditStore
from advanced_agent.time_service import TimeService


class AuditAgent:
    """Independent review layer.

    First version is intentionally rule-based. It can later be replaced by an
    LLM-backed reviewer without changing supervisor/main interfaces.
    """

    dangerous_fragments = (
        "rm -rf /",
        "sudo rm",
        "mkfs",
        "dd if=",
        "chmod -R 777 /",
        "curl | sh",
        "wget | sh",
        "git reset --hard",
    )

    def __init__(self, store: AuditStore, time: TimeService) -> None:
        self.store = store
        self.time = time

    def review(self, request: AuditRequest) -> AuditResult:
        text = str(request.payload).lower()
        decision = ReviewDecision.ALLOW
        reason = "allowed by first-pass audit rules"
        for fragment in self.dangerous_fragments:
            if fragment in text:
                decision = ReviewDecision.STOP
                reason = f"dangerous fragment detected: {fragment}"
                break
        result = AuditResult(
            request_id=request.id,
            decision=decision,
            reason=reason,
            priority=CommandPriority.AUDIT,
            created_at_ms=self.time.wall_ms(),
        )
        self.store.record(request, result)
        return result
