from advanced_agent.interrupts import InterruptGate
from advanced_agent.models import AgentRole, Authority, ControlCommand, TaskSpec
from advanced_agent.runtime.app import RuntimeApp


def test_interactive_then_main_authoritative(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    session_id = app.create_session("test")
    request_id = app.handle_user_text(session_id, "讨论架构", workdir=str(tmp_path))
    stream = app.sessions.stream_for_request(request_id)
    assert [d.authority for d in stream] == [Authority.PROVISIONAL, Authority.AUTHORITATIVE]
    assert stream[-1].supersedes_seq == stream[0].seq


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


def test_request_can_return_interactive_before_main(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    session_id = app.create_session("test")
    request_id, quick = app.start_user_request(session_id, "hello")
    assert quick.authority == Authority.PROVISIONAL
    assert len(app.sessions.stream_for_request(request_id)) == 1
    main = app.finish_user_request(session_id, request_id, workdir=str(tmp_path))
    assert main.authority == Authority.AUTHORITATIVE
    assert len(app.sessions.stream_for_request(request_id)) == 2


def test_hook_scheduler_wakes_internally() -> None:
    from advanced_agent.hooks import HookKind, HookScheduler
    from advanced_agent.time_service import TimeService

    scheduler = HookScheduler(TimeService())
    hook = scheduler.schedule_in(HookKind.CHECK_STATE, target="main", delay_ms=0)
    due = scheduler.due()
    assert due and due[0].id == hook.id
    assert not hook.enabled
    assert scheduler.sleep_backoff_for_idle(2 * 60 * 60_000) == 3 * 60 * 60_000
