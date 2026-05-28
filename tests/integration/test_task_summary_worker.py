from advanced_agent.hooks import HookKind
from advanced_agent.models import TaskSpec
from advanced_agent.runtime.app import RuntimeApp


def test_task_summary_worker_summarizes_active_tasks(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="summary", workdir=str(tmp_path)))
    app.tasks.append_output(task_id, "stdout", "step 1 ok\n", app.time.wall_ms())
    app.tasks.append_output(task_id, "stderr", "warning: check config\n", app.time.wall_ms())
    run = app.task_summary_worker.summarize_active()
    assert run.summarized >= 1
    state = app.tasks.get_state(task_id)
    assert state is not None and "warning" in (state.latest_summary or "")
    history = app.tasks.history(task_id)
    assert any(s["kind"] == "progress" for s in history["summaries"])


def test_check_tasks_hook_runs_summary_worker(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="summary", workdir=str(tmp_path)))
    app.tasks.append_output(task_id, "stdout", "hello task\n", app.time.wall_ms())
    app.hooks.schedule_in(HookKind.CHECK_TASKS, target="tasks", now_ms=app.time.wall_ms(), delay_ms=0)
    result = app.automation.tick()
    assert any(action.startswith("check_tasks:summarized") for action in result.actions)
    assert app.tasks.get_state(task_id).latest_summary
