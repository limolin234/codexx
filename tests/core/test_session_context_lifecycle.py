from advanced_agent.models import Message
from advanced_agent.runtime.app import RuntimeApp


def test_default_session_resumes_existing_session(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    first = app.default_session("default")
    second = app.default_session("default")
    assert first == second
    fresh = app.create_session("default")
    assert fresh != first


def test_context_clear_and_rollback_are_non_destructive(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session("default")
    base = app.time.wall_ms()
    ids = []
    for i in range(4):
        msg = Message(session_id=sid, request_id=f"r{i}", role="user", content=f"msg {i}", created_at_ms=base + i)
        ids.append(msg.id)
        app.sessions.append_message(msg)
    assert app.sessions.uncompacted_char_count(sid) > 0
    cleared = app.clear_context_before_ms(sid, base + 1)
    assert cleared == 2
    active = app.sessions.session_messages(sid)
    assert [m.content for m in active] == ["msg 2", "msg 3"]
    rolled = app.rollback_context_to_ms(sid, base + 2)
    assert rolled == 1
    active = app.sessions.session_messages(sid)
    assert [m.content for m in active] == ["msg 2"]
    all_messages = app.sessions.session_messages(sid, include_compacted=True)
    assert len(all_messages) == 4
    stats = app.sessions.context_stats(sid)
    assert stats["total_messages"] == 4
    assert stats["active_messages"] == 1
    assert stats["compacted_messages"] == 3


def test_default_session_falls_back_to_latest_active_session(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    old = app.create_session("cli")
    resumed = app.default_session("default")
    assert resumed == old
