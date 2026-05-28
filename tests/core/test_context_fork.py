from advanced_agent.context_fork import ContextForkBuilder, ContextForkSpec
from advanced_agent.models import Message
from advanced_agent.runtime.app import RuntimeApp


def test_context_fork_builder_is_bounded_and_cacheable(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("fork")
    app.sessions.append_message(Message(session_id=sid, request_id="r", role="user", content="架构要可维护", created_at_ms=app.time.wall_ms()))
    builder = ContextForkBuilder(app.context_builder)
    spec = ContextForkSpec(parent_session_id=sid, request_id="r", goal="实现 CLI 输出优化", focus="cli")
    fork1 = builder.build(spec)
    fork2 = builder.build(spec)
    assert fork1.cache_key == fork2.cache_key
    text = "\n".join(m.content or "" for m in fork1.messages)
    assert "实现 CLI 输出优化" in text
    assert "架构要可维护" in text
