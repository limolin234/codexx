from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.stores.sqlite_store import SQLiteStore


@dataclass(slots=True)
class HealthStatus:
    ok: bool
    checks: dict[str, bool]
    details: dict[str, str]


class HealthChecker:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def check(self) -> HealthStatus:
        checks: dict[str, bool] = {}
        details: dict[str, str] = {}
        try:
            row = self.db.query_one("SELECT 1 AS ok")
            checks["sqlite"] = bool(row and row["ok"] == 1)
            details["sqlite"] = "ok"
        except Exception as exc:  # pragma: no cover - defensive boundary
            checks["sqlite"] = False
            details["sqlite"] = repr(exc)
        return HealthStatus(ok=all(checks.values()), checks=checks, details=details)
