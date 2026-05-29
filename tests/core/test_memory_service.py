import json

from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.llm import ChatMessage, ChatResponse, ToolCall
from advanced_agent.major_memory_writer import MajorModelMemoryWriter
from advanced_agent.profile_model import LLMProfileMaintainer


def test_memory_service_write_search_hydrates_content_and_dedups_labels(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    result = app.memory.write(
        summary="Codex MCP should read previous records",
        content="Previous record content: use MCP context.get before context-dependent answers.",
        scope="project:mcp",
        type="decision",
    )
    assert result.created

    hits = app.memory.search("previous records context", scope="project:mcp", top_k=5)
    assert len([hit for hit in hits if hit.memory_id == result.memory_id]) == 1
    assert hits[0].content and "context.get" in hits[0].content
    assert hits[0].labels and "semantic" in hits[0].labels


def test_memory_service_recent_lists_without_query(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.memory.write(summary="first durable note", scope="project:recent", source_id="1")
    app.memory.write(summary="second durable note", scope="project:recent", source_id="2")

    recent = app.memory.recent(scope="project:recent", limit=2)
    assert len(recent) == 2
    assert [item.summary for item in recent] == ["second durable note", "first durable note"]


def test_memory_lifecycle_supersede_archive_and_purge(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    old = app.memory.write(
        summary="old inferred user trait",
        content="Old trait content",
        scope="project:lifecycle",
        type="user_trait",
        source_strength="wrapper_inference",
        stability="situational",
        metadata={"evidence": "weak observation"},
    )
    new = app.memory.write(
        summary="new explicit user trait",
        content="New trait content",
        scope="project:lifecycle",
        type="user_trait",
        source_strength="explicit_user",
        stability="stable",
        supersedes_id=old.memory_id,
        metadata={"evidence": "user correction"},
    )
    assert new.created

    old_record = app.memory.get(old.memory_id, include_inactive=True)
    assert old_record is not None
    assert old_record.status == "superseded"
    assert old_record.superseded_by == new.memory_id
    assert app.memory.get(old.memory_id) is None

    found = app.memory.search("old inferred trait", scope="project:lifecycle", top_k=5)
    assert all(record.memory_id != old.memory_id for record in found)

    archived = app.memory.archive_inactive_indexes(limit=10)
    assert archived == 1
    archived_old = app.memory.get(old.memory_id, include_inactive=True)
    assert archived_old is not None
    assert archived_old.status == "archived"
    assert archived_old.archived_at_ms is not None
    assert archived_old.labels == {}

    deleted = app.memory.write(summary="delete me", scope="project:lifecycle", type="note")
    assert app.memory.deactivate(deleted.memory_id, status="deleted")
    purged = app.memory.purge_deleted(older_than_ms=app.time.wall_ms() + 1, limit=10)
    assert purged == 1
    assert app.memory.get(deleted.memory_id, include_inactive=True) is None


def test_memory_mark_used_updates_usage_metadata(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    written = app.memory.write(summary="usage tracked memory", scope="project:usage", type="note")
    found = app.memory.search("usage tracked", scope="project:usage", top_k=1)
    assert found and found[0].memory_id == written.memory_id
    app.memory.mark_used([item.memory_id for item in found])
    record = app.memory.get(written.memory_id)
    assert record is not None
    assert record.usage_count >= 1
    assert record.last_used_at_ms is not None


def test_memory_maintenance_prunes_compacted_raw_and_updates_profile(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("maintenance")
    request_id, _ = app.start_user_request(sid, "记忆和画像要自动维护")
    msg = app.sessions.latest_message(sid, role="user")
    assert msg is not None
    app.sessions.mark_compacted_before(sid, msg.id)
    old_ms = app.time.wall_ms() - 10 * 24 * 60 * 60 * 1000
    app.db.execute("UPDATE messages SET created_at_ms=? WHERE session_id=?", (old_ms, sid))
    result = app.memory_maintenance.run(session_id=sid, scope="project:maintenance", raw_retention_ms=1, limit=10)
    assert result.profile_id is not None
    assert result.pruned_raw_rows >= 1
    assert app.sessions.session_messages(sid, include_compacted=True) == []

    # Default RuntimeApp has no memory_write_model configured, so the small observer must not write durable traits.
    traits = app.memory.recent(scope="project:maintenance", type="user_trait", limit=5)
    assert traits == []
    overlay = app.overlays.overlays_for("project:maintenance", "main", max_total_chars=1000)
    raw_log = app.memory.write(
        summary="deprecated raw terminal transcript",
        content="large noisy terminal transcript",
        scope="project:maintenance",
        type="codex_interactive_log",
    )
    result = app.memory_maintenance.run(session_id=sid, scope="project:maintenance", raw_retention_ms=1, limit=10)
    assert result.purged_raw_log_memories == 1
    assert app.memory.get(raw_log.memory_id, include_inactive=True) is None


class FakeProfileModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = []

    def chat(self, messages: list[ChatMessage]) -> str:
        self.calls.append(messages)
        return json.dumps(self.payload, ensure_ascii=False)


class FakeMajorToolModel:
    def __init__(self, tool_args: list[dict]) -> None:
        self.tool_args = tool_args
        self.calls = []

    def chat_complete(self, messages, tools=None, tool_choice=None):
        self.calls.append((messages, tools, tool_choice))
        return ChatResponse(tool_calls=[
            ToolCall(id=f"call_{idx}", name="memory_profile_patch", arguments=json.dumps(args, ensure_ascii=False))
            for idx, args in enumerate(self.tool_args)
        ])


def test_llm_profile_maintainer_writes_distilled_vector_trait(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    model = FakeProfileModel({
        "patches": [
            {
                "action": "add",
                "summary": "User prefers vector memory as authoritative profile store",
                "evidence": "summary only first injection; real profile in vector db",
                "confidence": 0.91,
                "importance": 0.82,
                "stability": "stable",
                "source_strength": "explicit_user",
                "metadata": {"kind": "preference", "memory_type": "preference"},
            }
        ]
    })
    major = FakeMajorToolModel(model.payload["patches"])
    app.preferences.maintainer = LLMProfileMaintainer(model)  # type: ignore[arg-type]
    app.preferences.major_writer = MajorModelMemoryWriter(major)  # type: ignore[arg-type]
    sid = app.create_session("profile-model")
    app.start_user_request(sid, "summary 只做第一次注入，真正复杂画像靠向量数据库维护")

    profile_id = app.preferences.update_from_session(sid, scope="project:profile-model")

    assert profile_id.startswith("profile_")
    assert model.calls
    assert major.calls
    records = app.memory.recent(scope="project:profile-model", type="preference", limit=5)
    assert len(records) == 1
    assert records[0].summary == "User prefers vector memory as authoritative profile store"
    assert records[0].source_strength == "explicit_user"
    assert records[0].metadata and records[0].metadata["maintainer"] == "wrapper"
    overlay = app.overlays.overlays_for("project:profile-model", "main", max_total_chars=1000)[0]
    assert "Lightweight startup user-profile hints" in overlay
    assert "authoritative profile store" in overlay


def test_llm_profile_maintainer_can_supersede_existing_trait(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    old = app.memory.write(
        summary="Old profile trait",
        content="old",
        scope="project:profile-model",
        type="user_trait",
        source_strength="user_behavior",
        confidence=0.9,
        importance=0.7,
    )
    model = FakeProfileModel({
        "patches": [
            {
                "action": "update",
                "target_memory_id": old.memory_id,
                "summary": "Updated profile trait",
                "evidence": "new correction",
                "confidence": 0.93,
                "importance": 0.78,
                "source_strength": "explicit_user",
                "metadata": {"kind": "profile_trait"},
            }
        ]
    })
    major = FakeMajorToolModel(model.payload["patches"])
    app.preferences.maintainer = LLMProfileMaintainer(model)  # type: ignore[arg-type]
    app.preferences.major_writer = MajorModelMemoryWriter(major)  # type: ignore[arg-type]
    sid = app.create_session("profile-model")
    app.start_user_request(sid, "更新旧画像")

    app.preferences.update_from_session(sid, scope="project:profile-model")

    old_record = app.memory.get(old.memory_id, include_inactive=True)
    assert old_record is not None
    assert old_record.status == "superseded"
    assert old_record.superseded_by is not None
    new_record = app.memory.get(old_record.superseded_by)
    assert new_record is not None
    assert new_record.summary == "Updated profile trait"


def test_small_model_observer_without_major_writer_does_not_write_durable_trait(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    model = FakeProfileModel({
        "patches": [{
            "action": "add",
            "summary": "Hallucinated small-model trait",
            "evidence": "weak",
            "confidence": 0.99,
            "importance": 0.9,
            "source_strength": "user_behavior",
        }]
    })
    app.preferences.maintainer = LLMProfileMaintainer(model)  # type: ignore[arg-type]
    sid = app.create_session("profile-model")
    app.start_user_request(sid, "普通一句话")

    app.preferences.update_from_session(sid, scope="project:no-major")

    assert model.calls
    assert app.memory.recent(scope="project:no-major", type="user_trait", limit=5) == []
