from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Any

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore, dumps, loads
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class RuntimeEvent:
    type: str
    source: str
    payload: dict[str, Any]
    created_at_ms: int
    mono_ms: int
    id: str = field(default_factory=lambda: new_id("evt"))


class EventStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def append(self, event: RuntimeEvent) -> None:
        self.db.execute(
            "INSERT INTO runtime_events(id,type,source,payload_json,created_at_ms,mono_ms) VALUES(?,?,?,?,?,?)",
            (event.id, event.type, event.source, dumps(event.payload), event.created_at_ms, event.mono_ms),
        )

    def recent(self, limit: int = 50) -> list[RuntimeEvent]:
        rows = self.db.query_all("SELECT * FROM runtime_events ORDER BY created_at_ms DESC LIMIT ?", (limit,))
        events = [
            RuntimeEvent(
                id=row["id"],
                type=row["type"],
                source=row["source"],
                payload=loads(row["payload_json"]) or {},
                created_at_ms=row["created_at_ms"],
                mono_ms=row["mono_ms"],
            )
            for row in rows
        ]
        return list(reversed(events))


EventHandler = Callable[[RuntimeEvent], None]


class EventBus:
    """Persistent in-process event bus.

    Every event is stored before handlers run. This makes handler failures less
    likely to lose critical runtime history.
    """

    def __init__(self, store: EventStore, time: TimeService) -> None:
        self.store = store
        self.time = time
        self.handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    def publish(self, type_: str, source: str, payload: dict[str, Any] | None = None) -> RuntimeEvent:
        event = RuntimeEvent(
            type=type_,
            source=source,
            payload=payload or {},
            created_at_ms=self.time.wall_ms(),
            mono_ms=self.time.monotonic_ms(),
        )
        self.store.append(event)
        for handler in self.handlers.get(type_, []):
            handler(event)
        for handler in self.handlers.get("*", []):
            handler(event)
        return event
