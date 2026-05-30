from __future__ import annotations

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore
from advanced_agent.time_service import TimeService


class InjectionLedger:
    """Session-local record of content already injected through runtime tools.

    This prevents wrapper-level repeated context injection without asking the
    model to reason about duplicates. It tracks stable item identifiers such as
    memory_id, profile_key, and message/line ids.
    """

    def __init__(self, db: SQLiteStore, time: TimeService) -> None:
        self.db = db
        self.time = time

    def seen_ids(self, session_id: str, caller_session_id: str, item_kind: str) -> set[str]:
        rows = self.db.query_all(
            """SELECT item_id FROM session_injection_ledger
            WHERE session_id=? AND caller_session_id=? AND item_kind=?""",
            (session_id, caller_session_id or "", item_kind),
        )
        return {str(row["item_id"]) for row in rows}

    def mark_many(
        self,
        *,
        session_id: str,
        caller_session_id: str,
        item_kind: str,
        items: list[tuple[str, str | None]],
        source_tool: str = "context_get",
    ) -> None:
        if not items:
            return
        now = self.time.wall_ms()
        with self.db.transaction():
            for item_id, item_version in items:
                self.db.execute(
                    """INSERT INTO session_injection_ledger
                    (id,session_id,caller_session_id,item_kind,item_id,item_version,source_tool,injected_at_ms)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(session_id, caller_session_id, item_kind, item_id)
                    DO UPDATE SET item_version=excluded.item_version, source_tool=excluded.source_tool, injected_at_ms=excluded.injected_at_ms""",
                    (new_id("inj"), session_id, caller_session_id or "", item_kind, item_id, item_version, source_tool, now),
                )
