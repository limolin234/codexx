from advanced_agent.interrupts import InterruptGate
from advanced_agent.models import AgentRole, Authority, ControlCommand, TaskSpec
from advanced_agent.runtime.app import RuntimeApp


def test_record_user_message_does_not_run_internal_chat_agent(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    session_id = app.create_session("test")
    request_id = app.record_user_message(session_id, "讨论架构")
    assert app.sessions.message_for_request(session_id, request_id, role="user") is not None
    assert app.sessions.stream_for_request(request_id) == []


def test_supervisor_spawns_task_with_audit(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="safe task", workdir=str(tmp_path)))
    state = app.supervisor.get_task_state(task_id)
    assert state is not None
    assert state.status == "queued"


def test_audit_blocks_dangerous_task(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    try:
        app.supervisor.spawn_task(TaskSpec(goal="run rm -rf /", workdir=str(tmp_path)))
    except PermissionError as exc:
        assert "dangerous" in str(exc)
    else:
        raise AssertionError("dangerous task should be blocked")


def test_user_interrupt_cooldown(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="safe", workdir=str(tmp_path)))
    assert app.supervisor.request_task_control(task_id, ControlCommand.STOP, AgentRole.INTERACTIVE)
    assert app.supervisor.request_task_control(task_id, ControlCommand.STOP, AgentRole.INTERACTIVE)
    assert app.supervisor.request_task_control(task_id, ControlCommand.STOP, AgentRole.INTERACTIVE)
    assert not app.supervisor.request_task_control(task_id, ControlCommand.STOP, AgentRole.INTERACTIVE)


def test_record_user_message_schedules_maintenance(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    session_id = app.create_session("test")
    request_id = app.record_user_message(session_id, "hello")
    assert app.sessions.message_for_request(session_id, request_id, role="user") is not None
    rows = app.db.query_all("SELECT kind FROM runtime_hooks WHERE target=?", (f"session:{session_id}",))
    assert {row["kind"] for row in rows} >= {"preference_maintenance", "compact_memory", "memory_maintenance"}


def test_hook_scheduler_wakes_internally() -> None:
    from advanced_agent.hooks import HookKind, HookScheduler
    from advanced_agent.time_service import TimeService

    scheduler = HookScheduler(TimeService())
    hook = scheduler.schedule_in(HookKind.CHECK_STATE, target="main", delay_ms=0)
    due = scheduler.due()
    assert due and due[0].id == hook.id
    assert not hook.enabled
    assert scheduler.sleep_backoff_for_idle(2 * 60 * 60_000) == 3 * 60 * 60_000
