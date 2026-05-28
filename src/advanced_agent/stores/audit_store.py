from __future__ import annotations

from advanced_agent.models import AuditRequest, AuditResult
from advanced_agent.stores.sqlite_store import SQLiteStore, dumps


class AuditStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def record(self, request: AuditRequest, result: AuditResult) -> None:
        self.db.execute(
            """INSERT INTO audit_reviews
            (id,subject_type,subject_id,action,requested_by,request_payload_json,decision,reason,priority,created_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                result.id,
                request.subject_type,
                request.subject_id,
                request.action,
                request.requested_by.value,
                dumps(request.payload),
                result.decision.value,
                result.reason,
                int(result.priority),
                result.created_at_ms,
            ),
        )


class ControlStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def add_command(self, target_type: str, target_id: str, command: str, priority: int, created_by: str, now_ms: int) -> str:
        from advanced_agent.models import new_id

        command_id = new_id("cmd")
        self.db.execute(
            """INSERT INTO control_commands(id,target_type,target_id,command,priority,status,created_by,created_at_ms)
            VALUES(?,?,?,?,?,?,?,?)""",
            (command_id, target_type, target_id, command, priority, "pending", created_by, now_ms),
        )
        return command_id
