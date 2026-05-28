import json

from advanced_agent.capability_executor import CapabilityRequest, OpenAIToolAdapter
from advanced_agent.hooks import HookKind
from advanced_agent.models import AgentRole, TaskSpec
from advanced_agent.runtime.app import RuntimeApp


def test_capability_executor_reads_task_state_tail_history(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="safe", workdir=str(tmp_path)))
    app.tasks.append_output(task_id, "stdout", "hello\n", app.time.wall_ms())
    state = app.capability_executor.execute(CapabilityRequest("task_state", AgentRole.MAIN, {"task_id": task_id}))
    assert state.ok
    assert state.data["state"]["status"] == "queued"
    tail = app.capability_executor.execute(CapabilityRequest("task_tail", AgentRole.MAIN, {"task_id": task_id, "limit": 5}))
    assert tail.ok and "hello" in tail.data["tail"]
    history = app.capability_executor.execute(CapabilityRequest("task_history", AgentRole.MAIN, {"task_id": task_id}))
    assert history.ok and history.data["history"]["state"]["task_id"] == task_id


def test_capability_executor_memory_and_hook(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.remember("main agent is semantic authority", scope="project:cap", type_="decision")
    mem = app.capability_executor.execute(CapabilityRequest("memory_search", AgentRole.MAIN, {"query": "semantic authority", "scope": "project:cap"}))
    assert mem.ok and mem.data["hits"]
    hook = app.capability_executor.execute(CapabilityRequest("hook_schedule", AgentRole.MAIN, {"kind": HookKind.CHECK_STATE.value, "target": "main", "delay_ms": 0, "payload": {"x": 1}}))
    assert hook.ok and hook.data["hook_id"].startswith("hook_")
    assert app.automation.tick().fired == 1


def test_capability_executor_spawn_task_uses_audit(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    ok = app.capability_executor.execute(CapabilityRequest("spawn_task", AgentRole.MAIN, {"goal": "safe task", "workdir": str(tmp_path)}))
    assert ok.ok and ok.data["task_id"].startswith("task_")
    blocked = app.capability_executor.execute(CapabilityRequest("spawn_task", AgentRole.MAIN, {"goal": "run rm -rf /", "workdir": str(tmp_path)}))
    assert not blocked.ok
    assert "dangerous" in (blocked.error or "")


def test_openai_tool_adapter_roundtrip() -> None:
    schemas = OpenAIToolAdapter.tool_schemas(["task_tail", "memory_search"])
    assert [s["function"]["name"] for s in schemas] == ["task_tail", "memory_search"]
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "task_tail", "arguments": json.dumps({"task_id": "task_1", "limit": 10})},
    }
    req = OpenAIToolAdapter.request_from_tool_call(tool_call, AgentRole.MAIN, now_ms=123)
    assert req.capability == "task_tail"
    assert req.arguments["limit"] == 10
    assert req.external_call_id == "call_1"


def test_capability_executor_role_permissions(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    denied = app.capability_executor.execute(CapabilityRequest("spawn_task", AgentRole.INTERACTIVE, {"goal": "safe", "workdir": str(tmp_path)}))
    assert not denied.ok
    assert "not allowed" in (denied.error or "")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="safe", workdir=str(tmp_path)))
    allowed = app.capability_executor.execute(CapabilityRequest("task_state", AgentRole.INTERACTIVE, {"task_id": task_id}))
    assert allowed.ok


def test_capability_executor_audits_interrupt_request(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="safe", workdir=str(tmp_path)))
    result = app.capability_executor.execute(CapabilityRequest("interrupt_request", AgentRole.MAIN, {"target_id": task_id, "command": "stop"}))
    assert result.ok and result.data["accepted"] is True
    rows = app.db.query_all("SELECT action, requested_by FROM audit_reviews WHERE subject_id=?", (task_id,))
    assert any(row["action"] == "interrupt_request" and row["requested_by"] == "main" for row in rows)
