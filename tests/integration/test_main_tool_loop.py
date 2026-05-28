from advanced_agent.llm import ChatResponse, ToolCall
from advanced_agent.runtime.app import RuntimeApp


class FakeToolModel:
    def __init__(self) -> None:
        self.calls = 0
        self.seen_tools = []

    def chat(self, messages):
        return "unused"

    def chat_complete(self, messages, tools=None, tool_choice=None):
        self.calls += 1
        self.seen_tools.append(tools or [])
        if self.calls == 1:
            return ChatResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="memory_search", arguments='{"query":"semantic authority","scope":"project:test","top_k":3}')],
            )
        assert any(m.role == "tool" and "semantic authority" in (m.content or "") for m in messages)
        return ChatResponse(content="我查了记忆：main agent 是语义核心，interactive 只负责快速反馈。")


def test_main_agent_executes_official_tool_call_through_capability_executor(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.remember("main agent semantic authority; interactive is quick feedback", scope="project:test", type_="decision")
    fake = FakeToolModel()
    app.main.model = fake
    session_id = app.create_session("tool-loop")
    request_id = app.handle_user_text(session_id, "查一下 main 和 interactive 的分工", workdir=str(tmp_path))
    assert fake.calls == 2
    rendered = app.sessions.stream_for_request(request_id)[-1]
    assert "main agent" not in rendered.text
    assert "语义核心" in rendered.text
    decision = app.decisions.latest_for_request(session_id, request_id)
    assert decision is not None
    assert decision.task_requests[0]["capability"] == "memory_search"
    assert decision.task_requests[0]["ok"] is True
    assert any(schema["function"]["name"] == "memory_search" for schema in fake.seen_tools[0])


class AsyncFakeToolModel:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_complete_async(self, messages, tools=None, tool_choice=None):
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(content=None, tool_calls=[ToolCall(id="call_async", name="memory_search", arguments='{"query":"async memory","scope":"project:async"}')])
        assert any(m.role == "tool" for m in messages)
        return ChatResponse(content="异步 main 已经通过工具查到 async memory。")

    def chat_complete(self, messages, tools=None, tool_choice=None):
        raise AssertionError("sync path should not be used")

    def chat(self, messages):
        raise AssertionError("sync chat should not be used")


def test_background_main_uses_async_tool_loop(tmp_path) -> None:
    import asyncio

    async def run() -> None:
        app = RuntimeApp.create(tmp_path / "state.sqlite")
        app.remember("async memory", scope="project:async", type_="note")
        fake = AsyncFakeToolModel()
        app.main.model = fake
        sid = app.create_session("async-tool")
        request_id, _ = await app.start_user_request_background(sid, "查 async memory", str(tmp_path))
        rendered = await app.wait_user_request(request_id, timeout_seconds=2)
        assert "异步 main" in rendered.text
        assert fake.calls == 2
        decision = app.decisions.latest_for_request(sid, request_id)
        assert decision is not None
        assert decision.task_requests[0]["tool_call_id"] == "call_async"

    asyncio.run(run())
