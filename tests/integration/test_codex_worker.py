import asyncio
import json
import sys

from advanced_agent.codex_worker import CodexCommandSpec, CodexJsonlParser, CodexTaskWorker
from advanced_agent.models import TaskSpec
from advanced_agent.processes import AsyncSubprocessRunner
from advanced_agent.stores.sqlite_store import SQLiteStore
from advanced_agent.stores.task_store import TaskStore
from advanced_agent.time_service import TimeService


def test_codex_jsonl_parser_item_completed() -> None:
    parser = CodexJsonlParser()
    event = parser.parse_line(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}}))
    assert event is not None
    assert event.type == "codex.item.agent_message"


def test_codex_worker_fake_jsonl_process(tmp_path) -> None:
    async def run() -> None:
        time = TimeService()
        db = SQLiteStore(tmp_path / "state.sqlite")
        db.init_schema()
        tasks = TaskStore(db)
        task_id = tasks.create_task(TaskSpec(goal="fake", workdir=str(tmp_path)), time.wall_ms())
        runner = AsyncSubprocessRunner(time)
        worker = CodexTaskWorker(runner, tasks, time)
        fake_lines = [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}},
        ]
        code = "import json,sys; lines=%r; [print(json.dumps(x), flush=True) for x in lines]" % fake_lines
        handle = await worker.start(task_id, "fake", tmp_path, command=[sys.executable, "-c", code])
        rc = await worker.wait(handle)
        assert rc == 0
        state = tasks.get_state(task_id)
        assert state is not None and state.status == "completed"
        tail = tasks.get_tail(task_id)
        assert "thread.started" in tail
        rows = db.query_all("SELECT type FROM task_events WHERE task_id=? ORDER BY created_at_ms", (task_id,))
        types = [row["type"] for row in rows]
        assert "codex.thread.started" in types
        assert "codex.item.agent_message" in types
        assert "codex.turn.completed" in types
        assert "codex.process.exit" in types
        history = tasks.history(task_id)
        assert any(s["kind"] == "codex_agent_message" for s in history["summaries"])
        assert any(s["kind"] == "usage" for s in history["summaries"])
        assert any(s["kind"] == "final" for s in history["summaries"])

    asyncio.run(run())


def test_codex_command_spec_builds_policy_args(tmp_path) -> None:
    time = TimeService()
    db = SQLiteStore(tmp_path / "state.sqlite")
    db.init_schema()
    worker = CodexTaskWorker(AsyncSubprocessRunner(time), TaskStore(db), time)
    cmd = worker.build_command(CodexCommandSpec(prompt="do it", workdir=tmp_path, sandbox="read-only", approval="never", extra_args=("--ephemeral",)))
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "--sandbox" in cmd and "read-only" in cmd
    assert "--ask-for-approval" in cmd and "never" in cmd
    assert "--ephemeral" in cmd
    assert cmd[-1] == "do it"
