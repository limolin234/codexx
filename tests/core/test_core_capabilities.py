from advanced_agent.capability_executor import CapabilityRequest, OpenAIToolAdapter
from advanced_agent.models import AgentRole, TaskSpec
from advanced_agent.runtime.app import RuntimeApp


def test_project_info_capability_returns_project_root(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    result = app.capability_executor.execute(CapabilityRequest("project_info", AgentRole.MAIN, {}))
    assert result.ok
    assert result.data["cwd"]
    assert result.data["project_root"]


def test_task_list_capability_finds_recent_task_without_id(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    task_id = app.supervisor.spawn_task(TaskSpec(goal="inspect", workdir=str(tmp_path)))
    result = app.capability_executor.execute(CapabilityRequest("task_list", AgentRole.MAIN, {"limit": 5}))
    assert result.ok
    assert any(row["id"] == task_id for row in result.data["tasks"])


def test_openai_tool_adapter_exports_project_and_task_list() -> None:
    names = [tool["function"]["name"] for tool in OpenAIToolAdapter.tool_schemas(["project_info", "task_list"])]
    assert names == ["project_info", "task_list"]
