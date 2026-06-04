from advanced_agent.hooks import HookKind
from advanced_agent.runtime.app import RuntimeApp


def test_hook_store_and_automation_preference_update(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("auto")
    app.record_user_message(sid, "架构和模块解耦很重要，不要急着 demo")
    hook_id = app.hooks.ensure_unique(
        HookKind.PREFERENCE_MAINTENANCE,
        target=f"session:{sid}",
        now_ms=app.time.wall_ms(),
        delay_ms=0,
        payload={"session_id": sid, "scope": "project:auto"},
    )
    result = app.automation.tick()
    assert result.fired >= 1
    assert app.profiles.get_profile("project:auto") is not None
    events = app.events.store.recent(20)
    assert any(event.type == "hook.fired" and event.payload["hook_id"] == hook_id for event in events)


def test_user_request_schedules_maintenance(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("auto")
    app.record_user_message(sid, "hello")
    rows = app.db.query_all("SELECT * FROM runtime_hooks WHERE target=? AND enabled=1", (f"session:{sid}",))
    assert rows
