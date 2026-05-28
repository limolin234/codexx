from advanced_agent.context_budget import ContextBudget
from advanced_agent.compaction import ConversationCompactor
from advanced_agent.context_builder import ContextBuilder
from advanced_agent.models import Message
from advanced_agent.runtime.app import RuntimeApp


def test_conversation_compacts_over_threshold(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("compact")
    for i in range(12):
        app.sessions.append_message(Message(session_id=sid, request_id=f"r{i}", role="user", content="架构 可维护 " + ("x" * 200), created_at_ms=app.time.wall_ms() + i))
    budget = ContextBudget(max_chars=1000, compact_threshold_ratio=0.5, recent_ratio=0.3, retrieved_ratio=0.3)
    compactor = ConversationCompactor(app.sessions, app.vectors, app.alignment, app.time, budget=budget)
    result = compactor.maybe_compact(sid, scope="project:compact")
    assert result.compacted
    assert result.memory_id
    assert app.sessions.uncompacted_char_count(sid) < 12 * 200
    hits = app.search_memory("架构 可维护", scope="project:compact", top_k=3)
    assert hits


def test_context_builder_uses_recent_and_retrieved(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("ctx")
    app.remember("架构优先，可维护性优先", scope="project:ctx", type_="decision")
    for i in range(5):
        app.sessions.append_message(Message(session_id=sid, request_id=f"r{i}", role="user", content=f"recent {i}", created_at_ms=app.time.wall_ms() + i))
    builder = ContextBuilder(app.sessions, app.vectors, budget=ContextBudget(max_chars=1000))
    built = builder.build_for_main(sid, "架构", scope="project:ctx")
    assert built.recent_messages
    assert built.retrieved_memories
    assert built.total_chars <= 1000


def test_context_get_auto_compacts_and_retrieves_replacement_memory(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("auto-compact")
    # Force a tiny compaction budget for the app-level compactor used by context.get.
    app.compactor.budget = ContextBudget(max_chars=500, compact_threshold_ratio=0.5, recent_ratio=0.25, retrieved_ratio=0.5)
    for i in range(8):
        app.sessions.append_message(Message(session_id=sid, request_id=f"r{i}", role="user", content="自动注入 替换 相量标签 " + ("x" * 120), created_at_ms=app.time.wall_ms() + i))

    from advanced_agent.runtime_tools import RuntimeToolBridge

    ctx = RuntimeToolBridge(app).call(
        "context.get",
        {
            "session_id": sid,
            "query": "自动注入 相量标签",
            "scope": "project:auto",
            "mode": "full",
            "include_memory_content": True,
        },
    )
    assert ctx["ok"]
    assert ctx["maintenance"]["compacted"]
    assert ctx["maintenance"]["memory_id"]
    assert ctx["memories"]
    assert any("自动注入" in mem["content"] for mem in ctx["memories"])


def test_context_builder_injects_hydrated_memory_content(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("hydrated")
    app.memory.write(
        summary="短摘要",
        content="完整记忆内容：main agent 要自动注入检索到的相量数据库内容。",
        scope="project:hydrate",
        type="decision",
    )
    built = app.context_builder.build_for_main(sid, "相量数据库 自动注入", scope="project:hydrate")
    assert built.retrieved_memories
    assert "完整记忆内容" in (built.retrieved_memories[0].content or "")
