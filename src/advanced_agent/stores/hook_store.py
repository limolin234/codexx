from __future__ import annotations

from advanced_agent.hooks import HookKind, HookSpec
from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore, dumps, loads


class HookStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def schedule(self, hook: HookSpec, now_ms: int) -> str:
        self.db.execute(
            """INSERT OR REPLACE INTO runtime_hooks
            (id,kind,target,wake_at_ms,payload_json,repeat_ms,enabled,created_at_ms,updated_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (hook.id, str(hook.kind), hook.target, hook.wake_at_ms, dumps(hook.payload), hook.repeat_ms, int(hook.enabled), now_ms, now_ms),
        )
        return hook.id

    def schedule_in(self, kind: HookKind, target: str, now_ms: int, delay_ms: int, payload: dict | None = None, repeat_ms: int | None = None) -> str:
        hook = HookSpec(kind=kind, target=target, wake_at_ms=now_ms + delay_ms, payload=payload or {}, repeat_ms=repeat_ms)
        return self.schedule(hook, now_ms)

    def due(self, now_ms: int, limit: int = 50) -> list[HookSpec]:
        rows = self.db.query_all(
            "SELECT * FROM runtime_hooks WHERE enabled=1 AND wake_at_ms<=? ORDER BY wake_at_ms LIMIT ?",
            (now_ms, limit),
        )
        return [self._row_to_hook(row) for row in rows]

    def mark_fired(self, hook: HookSpec, now_ms: int) -> None:
        if hook.repeat_ms is None:
            self.db.execute("UPDATE runtime_hooks SET enabled=0, updated_at_ms=? WHERE id=?", (now_ms, hook.id))
        else:
            self.db.execute("UPDATE runtime_hooks SET wake_at_ms=?, updated_at_ms=? WHERE id=?", (now_ms + hook.repeat_ms, now_ms, hook.id))

    def ensure_unique(self, kind: HookKind, target: str, now_ms: int, delay_ms: int, payload: dict | None = None, repeat_ms: int | None = None) -> str:
        row = self.db.query_one("SELECT id FROM runtime_hooks WHERE kind=? AND target=? AND enabled=1", (str(kind), target))
        if row:
            self.db.execute(
                "UPDATE runtime_hooks SET wake_at_ms=?, payload_json=?, repeat_ms=?, updated_at_ms=? WHERE id=?",
                (now_ms + delay_ms, dumps(payload or {}), repeat_ms, now_ms, row["id"]),
            )
            return row["id"]
        return self.schedule_in(kind, target, now_ms, delay_ms, payload=payload, repeat_ms=repeat_ms)

    def _row_to_hook(self, row) -> HookSpec:
        return HookSpec(
            id=row["id"],
            kind=row["kind"],
            target=row["target"],
            wake_at_ms=row["wake_at_ms"],
            payload=loads(row["payload_json"]) or {},
            repeat_ms=row["repeat_ms"],
            enabled=bool(row["enabled"]),
        )
