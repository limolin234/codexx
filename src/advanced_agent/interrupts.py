from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.models import AgentRole, CommandPriority, ControlCommand
from advanced_agent.stores.sqlite_store import SQLiteStore
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class InterruptDecision:
    allowed: bool
    priority: CommandPriority
    reason: str
    cooldown_until_ms: int = 0


class InterruptGate:
    """Priority and cooldown gate for interruption requests."""

    def __init__(self, db: SQLiteStore, time: TimeService, max_user_interrupts: int = 3, window_ms: int = 10_000, cooldown_ms: int = 20_000) -> None:
        self.db = db
        self.time = time
        self.max_user_interrupts = max_user_interrupts
        self.window_ms = window_ms
        self.cooldown_ms = cooldown_ms

    def evaluate(self, scope: str, source: AgentRole, emergency: bool = False) -> InterruptDecision:
        now = self.time.wall_ms()
        priority = {
            AgentRole.AUDIT: CommandPriority.AUDIT,
            AgentRole.MAIN: CommandPriority.MAIN,
            AgentRole.INTERACTIVE: CommandPriority.INTERACTIVE,
        }.get(source, CommandPriority.USER)

        row = self.db.query_one("SELECT * FROM interrupt_state WHERE scope=?", (scope,))
        if row is None:
            self.db.execute(
                """INSERT INTO interrupt_state(scope,interrupt_enabled,user_interrupt_enabled,cooldown_until_ms,
                window_started_at_ms,interrupt_count,updated_at_ms) VALUES(?,?,?,?,?,?,?)""",
                (scope, 1, 1, 0, now, 0, now),
            )
            row = self.db.query_one("SELECT * FROM interrupt_state WHERE scope=?", (scope,))

        assert row is not None
        if not bool(row["interrupt_enabled"]):
            return InterruptDecision(False, priority, "interrupt disabled")

        if source not in (AgentRole.AUDIT, AgentRole.MAIN) and not emergency:
            cooldown_until = int(row["cooldown_until_ms"])
            if cooldown_until > now:
                return InterruptDecision(False, priority, "user interrupt cooldown active", cooldown_until)

        if source not in (AgentRole.AUDIT, AgentRole.MAIN):
            window_started = int(row["window_started_at_ms"])
            count = int(row["interrupt_count"])
            if now - window_started > self.window_ms:
                window_started = now
                count = 0
            count += 1
            cooldown_until = 0
            if count > self.max_user_interrupts and not emergency:
                cooldown_until = now + self.cooldown_ms
                self.db.execute(
                    """UPDATE interrupt_state SET window_started_at_ms=?, interrupt_count=?, cooldown_until_ms=?, updated_at_ms=?
                    WHERE scope=?""",
                    (window_started, count, cooldown_until, now, scope),
                )
                return InterruptDecision(False, priority, "too many user interrupts; cooldown enabled", cooldown_until)
            self.db.execute(
                "UPDATE interrupt_state SET window_started_at_ms=?, interrupt_count=?, updated_at_ms=? WHERE scope=?",
                (window_started, count, now, scope),
            )

        return InterruptDecision(True, priority, "allowed")
