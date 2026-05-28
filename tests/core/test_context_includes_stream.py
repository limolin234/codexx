from advanced_agent.models import AgentRole, Authority, Message, StreamDelta
from advanced_agent.runtime.app import RuntimeApp


def test_main_context_includes_authoritative_assistant_stream(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("ctx-stream")
    now = app.time.wall_ms()
    app.sessions.append_message(Message(session_id=sid, request_id="r1", role="user", content="之前在做什么", created_at_ms=now))
    app.sessions.append_stream_delta(StreamDelta(session_id=sid, request_id="r1", seq=1, writer=AgentRole.INTERACTIVE, authority=Authority.AUTHORITATIVE, text="我们刚才在调 CLI 上下文。", timestamp_ms=now + 1))
    built = app.context_builder.build_for_main(sid, "看到记录吗")
    joined = "\n".join(built.recent_messages)
    assert "之前在做什么" in joined
    assert "我们刚才在调 CLI 上下文" in joined


def test_prompt_tells_main_not_to_deny_visible_context(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    bundle = app.main.prompt_builder.main_decision("missing", "r", "看到记录吗")
    text = "\n".join(m.content or "" for m in bundle.messages)
    assert "不要声称完全没有上下文" in text
    assert "Recent context" in text
