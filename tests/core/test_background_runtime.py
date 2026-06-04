import time

from advanced_agent.hooks import HookKind
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.runtime.background import BackgroundRuntimeConfig, BackgroundRuntimeQueue


def test_background_runtime_queue_consumes_due_hooks(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    hook_id = app.hooks.schedule_in(
        HookKind.CHECK_STATE,
        target="test",
        now_ms=app.time.wall_ms(),
        delay_ms=0,
    )
    queue = BackgroundRuntimeQueue(
        app,
        BackgroundRuntimeConfig(enabled=True, tick_interval_seconds=0.05, hook_limit=5, exit_flush_seconds=0.2),
    )
    queue.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        row = app.db.query_one("SELECT enabled FROM runtime_hooks WHERE id=?", (hook_id,))
        if row is not None and int(row["enabled"]) == 0:
            break
        time.sleep(0.02)
    queue.stop()
    row = app.db.query_one("SELECT enabled FROM runtime_hooks WHERE id=?", (hook_id,))
    assert row is not None
    assert int(row["enabled"]) == 0


def test_background_runtime_queue_can_be_disabled(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    queue = BackgroundRuntimeQueue(app, BackgroundRuntimeConfig(enabled=False))
    queue.start()
    assert not queue.running


def test_background_runtime_stop_swallows_keyboard_interrupt(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    queue = BackgroundRuntimeQueue(app, BackgroundRuntimeConfig(enabled=True, exit_flush_seconds=0.1))

    class InterruptingThread:
        def join(self, timeout=None):
            raise KeyboardInterrupt

        def is_alive(self):
            return True

    queue._thread = InterruptingThread()  # type: ignore[assignment]
    queue.stop()
    events = app.events.store.recent(5)
    assert any(event.type == "runtime.background.stop_interrupted" for event in events)
