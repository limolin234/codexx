from advanced_agent.events import EventBus, EventStore
from advanced_agent.health import HealthChecker
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.stores.sqlite_store import SQLiteStore
from advanced_agent.time_service import TimeService


def test_event_bus_persists_before_dispatch(tmp_path) -> None:
    db = SQLiteStore(tmp_path / "state.sqlite")
    db.init_schema()
    store = EventStore(db)
    bus = EventBus(store, TimeService())
    seen = []
    bus.subscribe("demo", lambda event: seen.append(event.id))
    event = bus.publish("demo", "test", {"x": 1})
    assert seen == [event.id]
    recent = store.recent()
    assert recent[-1].id == event.id
    assert recent[-1].payload == {"x": 1}


def test_sqlite_transaction_rolls_back(tmp_path) -> None:
    db = SQLiteStore(tmp_path / "state.sqlite")
    db.init_schema()
    try:
        with db.transaction():
            db.conn.execute("INSERT INTO sessions(id,title,status,created_at_ms,updated_at_ms) VALUES('s','t','active',1,1)")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.query_one("SELECT * FROM sessions WHERE id='s'") is None


def test_runtime_health_and_events(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    assert app.health.check().ok
    sid = app.create_session("infra")
    app.handle_user_text(sid, "hello", workdir=str(tmp_path))
    events = app.events.store.recent(10)
    assert any(event.type == "session.created" for event in events)
    assert any(event.type == "main.decided" for event in events)
