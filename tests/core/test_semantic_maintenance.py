from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.llm import ChatResponse, ToolCall
from advanced_agent.semantic_worker import SemanticMaintenanceWorker


class FakeApprovalModel:
    def __init__(self) -> None:
        self.calls = []
        self.config = type("Config", (), {"model": "fake-approval"})()

    def chat_complete(self, messages, tools=None, tool_choice=None):
        self.calls.append((messages, tools, tool_choice))
        return ChatResponse(tool_calls=[
            ToolCall(
                id="call_1",
                name="semantic_memory_decision",
                arguments='{"approve": true, "reason": "durable handoff", "type": "handoff", "summary": "Semantic pipeline handoff", "content": "Approved semantic pipeline summary.", "importance": 0.72, "confidence": 0.88, "stability": "normal"}',
            )
        ])


class FakeSummaryModel:
    def __init__(self, text: str = "new checkpoint") -> None:
        self.text = text
        self.calls = []
        self.config = type("Config", (), {"model": "fake-summary"})()

    def chat(self, messages):
        self.calls.append(messages)
        return self.text


def test_semantic_maintenance_compacts_events_atomically(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("semantic")
    for idx in range(4):
        app.semantic_store.append_event(session_id=sid, kind="user_submit", text=f"用户消息 {idx}", now_ms=app.time.wall_ms())
        app.semantic_store.append_event(session_id=sid, kind="cleaned_tty_chunk", text=f"输出 {idx}", now_ms=app.time.wall_ms())

    result = app.semantic_maintenance.run(session_id=sid, scope="project:semantic", reason="test", force=False)

    assert result.tasks_created == 1
    assert result.tasks_processed == 1
    assert result.summaries_created == 1
    summary = app.semantic_store.latest_summary(sid, "project:semantic")
    assert summary is not None
    assert "用户消息" in summary
    assert app.semantic_store.unconsumed_user_submits(sid) <= 1


def test_semantic_maintenance_recovers_stale_running_task(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("semantic-stale")
    event = app.semantic_store.append_event(session_id=sid, kind="user_submit", text="需要恢复 stale task", now_ms=app.time.wall_ms())
    assert event is not None
    task_id = app.semantic_store.create_task(
        session_id=sid,
        scope="project:semantic",
        kind="semantic_compact",
        reason="test",
        from_seq=event.seq,
        to_seq=event.seq,
        input_hash="hash",
        now_ms=app.time.wall_ms(),
    )
    assert app.semantic_store.lock_task(task_id, app.time.wall_ms())
    old_ms = app.time.wall_ms() - 10 * 60 * 1000
    app.db.execute("UPDATE semantic_tasks SET locked_at_ms=?, updated_at_ms=? WHERE id=?", (old_ms, old_ms, task_id))

    result = app.semantic_maintenance.run(session_id=None, scope="project:semantic", reason="recover")

    assert result.tasks_processed == 1
    assert app.semantic_store.latest_summary(sid, "project:semantic") is not None


def test_semantic_maintenance_approval_writes_memory(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    approval = FakeApprovalModel()
    app.semantic_maintenance = SemanticMaintenanceWorker(app.semantic_store, app.time, model=None, memory=app.memory, approval_model=approval)  # type: ignore[arg-type]
    sid = app.create_session("semantic-approval")
    for idx in range(3):
        app.semantic_store.append_event(session_id=sid, kind="user_submit", text=f"重要设计 {idx}", now_ms=app.time.wall_ms())

    result = app.semantic_maintenance.run(session_id=sid, scope="project:semantic-approval", reason="session_close", force=True)

    assert result.candidates_created == 1
    assert result.candidates_processed == 1
    assert result.memories_written == 1
    assert approval.calls
    records = app.memory.recent(scope="project:semantic-approval", type="handoff", limit=5)
    assert len(records) == 1
    assert records[0].summary == "Semantic pipeline handoff"


def test_routine_semantic_compaction_does_not_create_memory_candidate(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("semantic-routine")
    for idx in range(3):
        app.semantic_store.append_event(session_id=sid, kind="user_submit", text=f"普通对话 {idx}", now_ms=app.time.wall_ms())

    result = app.semantic_maintenance.run(session_id=sid, scope="project:semantic-routine", reason="user_submit_3")

    assert result.summaries_created == 1
    assert result.candidates_created == 0


def test_semantic_summary_prompt_uses_append_only_cache_ledger(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    model = FakeSummaryModel("checkpoint one")
    app.semantic_maintenance = SemanticMaintenanceWorker(app.semantic_store, app.time, model=model, memory=app.memory, approval_model=None)  # type: ignore[arg-type]
    sid = app.create_session("semantic-cache")
    for idx in range(3):
        app.semantic_store.append_event(session_id=sid, kind="user_submit", text=f"第一批 {idx}", now_ms=app.time.wall_ms())

    app.semantic_maintenance.run(session_id=sid, scope="project:semantic-cache", reason="user_submit_3", force=True)
    assert model.calls
    first_user = model.calls[-1][1].content
    assert first_user is not None
    assert "CACHE_LEDGER_FORMAT: semantic_compact_v2_cache_ledger" in first_user
    assert "IMMUTABLE_PRIOR_SUMMARY_BLOCKS:\n\n(none)" in first_user
    assert "DYNAMIC_NEW_EVENTS:" in first_user

    model.text = "checkpoint two"
    for idx in range(3):
        app.semantic_store.append_event(session_id=sid, kind="user_submit", text=f"第二批 {idx}", now_ms=app.time.wall_ms())
    app.semantic_maintenance.run(session_id=sid, scope="project:semantic-cache", reason="user_submit_3", force=True)
    second_user = model.calls[-1][1].content
    assert second_user is not None
    assert "SUMMARY_BLOCK seq=1-3\ncheckpoint one" in second_user
    assert second_user.index("IMMUTABLE_PRIOR_SUMMARY_BLOCKS:") < second_user.index("DYNAMIC_NEW_EVENTS:")


def test_semantic_maintenance_degrades_without_api_keys(tmp_path) -> None:
    config = tmp_path / ".env.json"
    config.write_text(
        """
{
  "roles": {"memory_model": "small", "memory_write_model": "strong"},
  "models": {
    "small": {"provider": "openai_compatible", "model": "s", "base_url": "http://x/v1", "api_key_env": "MISSING_SMALL_KEY"},
    "strong": {"provider": "openai_compatible", "model": "b", "base_url": "http://x/v1", "api_key_env": "MISSING_STRONG_KEY"}
  }
}
""",
        encoding="utf-8",
    )
    app = RuntimeApp.create(tmp_path / "state.sqlite", config)
    assert app.semantic_maintenance.model is None
    assert app.semantic_maintenance.approval_model is None
    sid = app.create_session("semantic-no-key")
    app.semantic_store.append_event(session_id=sid, kind="user_submit", text="无 key 也应该能压缩", now_ms=app.time.wall_ms())

    result = app.semantic_maintenance.run(session_id=sid, scope="project:no-key", reason="session_close", force=True)

    assert result.summaries_created == 1
    assert result.candidates_created == 1
    assert result.candidates_processed == 1
    assert result.memories_written == 0
    row = app.db.query_one("SELECT status FROM semantic_memory_candidates WHERE session_id=?", (sid,))
    assert row is not None
    assert row["status"] == "awaiting_approval_model"
