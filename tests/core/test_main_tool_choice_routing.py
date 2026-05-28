from advanced_agent.llm import ChatResponse, ToolCall
from advanced_agent.runtime.app import RuntimeApp


class ToolChoiceModel:
    def __init__(self):
        self.first_tool_choice = None
        self.calls = 0
    def chat_complete(self, messages, tools=None, tool_choice=None):
        self.calls += 1
        if self.calls == 1:
            self.first_tool_choice = tool_choice
            name = tool_choice["function"]["name"] if isinstance(tool_choice, dict) else "task_list"
            return ChatResponse(content=None, tool_calls=[ToolCall(id="call_1", name=name, arguments="{}")])
        return ChatResponse(content="查到了。")
    def chat(self, messages):
        return "unused"


def test_main_routes_project_question_to_project_info_tool_choice(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    model = ToolChoiceModel()
    app.main.model = model
    sid = app.create_session("tool-choice")
    req, _ = app.start_user_request(sid, "你的工作路径是什么")
    app.finish_user_request(sid, req, str(tmp_path))
    assert model.first_tool_choice == {"type": "function", "function": {"name": "project_info"}}


def test_main_routes_task_question_to_task_list_tool_choice(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    model = ToolChoiceModel()
    app.main.model = model
    sid = app.create_session("tool-choice")
    req, _ = app.start_user_request(sid, "刚才任务怎么样了")
    app.finish_user_request(sid, req, str(tmp_path))
    assert model.first_tool_choice == {"type": "function", "function": {"name": "task_list"}}
