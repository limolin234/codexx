import asyncio
import json
import sys

from advanced_agent.models import AgentRole, ControlCommand, TaskSpec
from advanced_agent.runtime.app import RuntimeApp


def test_supervisor_starts_codex_backend_with_fake_jsonl(tmp_path) -> None:
    async def run() -> None:
        app = RuntimeApp.create(tmp_path / "state.sqlite")
        fake_lines = [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "backend ok"}},
            {"type": "turn.completed", "usage": {"input_tokens": 2, "output_tokens": 3}},
        ]
        code = "import json; lines=%r; [print(json.dumps(x), flush=True) for x in lines]" % fake_lines
        task_id = await app.supervisor.spawn_task_async(
            TaskSpec(goal="fake codex backend", workdir=str(tmp_path)),
            codex_command=[sys.executable, "-c", code],
        )
        waiter = app.supervisor.task_waiters[task_id]
        rc = await waiter
        assert rc == 0
        state = app.supervisor.get_task_state(task_id)
        assert state is not None and state.status == "completed"
        assert "backend ok" in app.supervisor.get_task_tail(task_id)
        history = app.tasks.history(task_id)
        assert any(event["type"] == "codex.process.exit" for event in history["events"])
        assert task_id in app.supervisor.task_handles
        assert task_id in app.supervisor.task_workers

    asyncio.run(run())


def test_supervisor_async_stop_stops_running_backend(tmp_path) -> None:
    async def run() -> None:
        app = RuntimeApp.create(tmp_path / "state.sqlite")
        code = "import time; print('started', flush=True); time.sleep(10)"
        task_id = await app.supervisor.spawn_task_async(
            TaskSpec(goal="long fake codex backend", workdir=str(tmp_path)),
            codex_command=[sys.executable, "-c", code],
        )
        await asyncio.sleep(0.1)
        accepted = await app.supervisor.request_task_control_async(task_id, ControlCommand.STOP, AgentRole.MAIN)
        assert accepted
        state = app.supervisor.get_task_state(task_id)
        assert state is not None
        assert state.status in {"failed", "stop"}
        assert "started" in app.supervisor.get_task_tail(task_id)

    asyncio.run(run())
