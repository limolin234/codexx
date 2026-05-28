from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore, dumps, loads


@dataclass(slots=True)
class MainDecision:
    session_id: str
    request_id: str
    intent: str
    decision_type: str
    internal_summary: str
    user_visible_instruction: str
    audit_status: str = "not_required"
    task_requests: list[dict[str, Any]] = field(default_factory=list)
    created_at_ms: int = 0
    id: str = field(default_factory=lambda: new_id("decision"))


class MainDecisionStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def add(self, decision: MainDecision) -> str:
        self.db.execute(
            """INSERT INTO main_decisions
            (id,session_id,request_id,intent,decision_type,internal_summary,user_visible_instruction,task_requests_json,audit_status,created_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                decision.id,
                decision.session_id,
                decision.request_id,
                decision.intent,
                decision.decision_type,
                decision.internal_summary,
                decision.user_visible_instruction,
                dumps(decision.task_requests),
                decision.audit_status,
                decision.created_at_ms,
            ),
        )
        return decision.id

    def latest_for_request(self, session_id: str, request_id: str) -> MainDecision | None:
        row = self.db.query_one(
            "SELECT * FROM main_decisions WHERE session_id=? AND request_id=? ORDER BY created_at_ms DESC LIMIT 1",
            (session_id, request_id),
        )
        if row is None:
            return None
        return MainDecision(
            id=row["id"],
            session_id=row["session_id"],
            request_id=row["request_id"],
            intent=row["intent"],
            decision_type=row["decision_type"],
            internal_summary=row["internal_summary"],
            user_visible_instruction=row["user_visible_instruction"],
            task_requests=loads(row["task_requests_json"]) or [],
            audit_status=row["audit_status"],
            created_at_ms=row["created_at_ms"],
        )
