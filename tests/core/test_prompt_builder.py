from advanced_agent.models import Message
from advanced_agent.runtime.app import RuntimeApp


def test_prompt_builder_uses_overlays_and_context(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("prompt")
    now = app.time.wall_ms()
    app.overlays.replace_overlay("project:advanced_agent", "main", "pref", "可维护性优先", now, priority=10)
    app.sessions.append_message(Message(session_id=sid, request_id="r", role="user", content="讨论架构", created_at_ms=now))
    bundle = app.main.prompt_builder.main_decision(sid, "r", "继续讨论架构")
    joined = "\n".join(m.content for m in bundle.messages)
    assert "可维护性优先" in joined
    assert "Recent context" in joined
    assert bundle.purpose == "main_decision"


def test_interactive_prompt_builder_is_restrictive(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    bundle = app.interactive.prompt_builder.interactive_quick("能不能调用工具？")
    text = "\n".join(m.content for m in bundle.messages)
    assert "不要声称已经执行工具" in text
    assert "不要说“主 agent”" in text
