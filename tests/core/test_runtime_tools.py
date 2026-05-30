from pathlib import Path

from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.runtime_tools import RuntimeToolBridge


def test_runtime_tool_bridge_memory_and_project(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    bridge = RuntimeToolBridge(app)
    policies = {spec.name: spec for spec in bridge.specs()}
    assert policies["memory.search"].auto_approve
    assert policies["memory.search"].risk == "safe_read"
    assert policies["memory.write"].auto_approve
    assert policies["memory.write"].risk == "safe_db_write"
    assert policies["workdir.chdir"].auto_approve
    assert policies["workdir.chdir"].risk == "safe_state_write"
    written = bridge.call("memory.write", {"summary": "MCP bridge memory", "scope": "project:mcp", "type": "note"})
    assert written["ok"]
    found = bridge.call("memory.search", {"query": "MCP bridge", "scope": "project:mcp", "top_k": 3})
    assert found["ok"] and found["data"]["hits"]
    project = bridge.call("project.info")
    assert project["ok"] and project["data"]["project_root"]


def test_runtime_tool_bridge_timer_and_event_wait(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    bridge = RuntimeToolBridge(app)
    timer = bridge.call("timer.schedule", {"delay_ms": 0, "reason": "test"})
    assert timer["ok"] and timer["hook_id"].startswith("hook_")
    app.automation.tick()
    event = bridge.call("event.wait", {"type": "hook.fired", "timeout_ms": 0})
    assert event["ok"] and event["event"] is not None


def test_runtime_tool_bridge_session_recent(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.start_user_request(sid, "hello")
    bridge = RuntimeToolBridge(app)
    recent = bridge.call("session.recent", {"session_id": sid})
    assert recent["ok"] and any("hello" in line for line in recent["lines"])


def test_runtime_tool_bridge_context_get_fuses_recent_and_memory(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.start_user_request(sid, "context hello")
    app.remember("context memory item", scope="project:ctx", type_="note")
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call("context.get", {"session_id": sid, "query": "context memory", "scope": "project:ctx", "mode": "full", "view": "debug"})
    assert ctx["ok"]
    assert any("context hello" in line for line in ctx["context_lines"])
    assert ctx["memories"]


def test_runtime_tool_bridge_context_get_supplement_skips_live_recent(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("supplement")
    for i in range(6):
        app.start_user_request(sid, f"turn {i}")
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call("context.get", {"session_id": sid, "query": "turn", "mode": "supplement", "live_recent_limit": 2, "recent_limit": 10, "view": "debug"})
    assert ctx["ok"]
    assert ctx["mode"] == "supplement"
    assert ctx["live_recent_skipped"] == 2
    assert any("turn 3" in line for line in ctx["context_lines"])
    assert all("turn 4" not in line and "turn 5" not in line for line in ctx["context_lines"])


def test_runtime_tool_bridge_context_get_excludes_noisy_logs_by_default(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.memory.write(summary="noisy terminal log memory", scope="project:ctx", type="codex_interactive_log", importance=0.9)
    app.memory.write(summary="clean design decision memory", scope="project:ctx", type="decision", importance=0.8)
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call("context.get", {"query": "memory", "scope": "project:ctx", "memory_top_k": 5, "view": "debug"})
    assert ctx["ok"]
    assert "codex_interactive_log" in ctx["excluded_memory_types"]
    assert all(item["type"] != "codex_interactive_log" for item in ctx["memories"])
    assert any(item["type"] == "decision" for item in ctx["memories"])

    with_logs = bridge.call("context.get", {"query": "memory", "scope": "project:ctx", "memory_top_k": 5, "include_log_memories": True})
    assert any(item["type"] == "codex_interactive_log" for item in with_logs["memories"])


def test_context_get_dedupes_injected_memories_and_context_lines(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("dedupe")
    app.start_user_request(sid, "older context line")
    app.start_user_request(sid, "live context line")
    app.memory.write(summary="dedupe memory item", scope="project:dedupe", type="decision")
    bridge = RuntimeToolBridge(app)
    args = {"session_id": sid, "query": "dedupe memory", "scope": "project:dedupe", "mode": "supplement", "live_recent_limit": 1, "caller_session_id": "codexsess_test"}
    first = bridge.call("context.get", args)
    second = bridge.call("context.get", args)
    assert first["context_lines"]
    assert first["memories"]
    assert second["context_lines"] == []
    assert second["memories"] == []


def test_context_get_returns_profile_hints_without_memory_metadata(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.memory.write(
        summary="Prefer compact answers and put detailed derivations in files when useful.",
        scope="project:profile",
        type="preference",
        importance=0.9,
        confidence=0.95,
        source_strength="explicit_user",
        metadata={"profile_key": "collaboration.answer_length"},
    )
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call("context.get", {"session_id": sid, "query": "ordinary project question", "scope": "project:profile", "caller_session_id": "codexsess_profile"})
    assert ctx["profile_hints"] == [
        {
            "profile_key": "collaboration.answer_length",
            "hint": "Prefer compact answers and put detailed derivations in files when useful.",
            "updated_at_ms": ctx["profile_hints"][0]["updated_at_ms"],
        }
    ]
    assert all(item["type"] != "preference" for item in ctx["memories"])
    again = bridge.call("context.get", {"session_id": sid, "query": "ordinary project question", "scope": "project:profile", "caller_session_id": "codexsess_profile"})
    assert again["profile_hints"] == []


def test_context_get_respects_include_profile_false(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.memory.write(
        summary="Prefer compact answers.",
        scope="project:profile",
        type="preference",
        importance=0.9,
        confidence=0.95,
        source_strength="explicit_user",
        metadata={"profile_key": "collaboration.compact"},
    )
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call(
        "context.get",
        {
            "session_id": sid,
            "query": "ordinary project question",
            "scope": "project:profile",
            "include_profile": False,
            "caller_session_id": "codexsess_profile_disabled",
        },
    )
    assert ctx["profile_hints"] == []


def test_context_get_does_not_inject_raw_profile_evidence(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.memory.write(
        summary="[profile_evidence] The user said one raw thing that is not distilled yet.",
        scope="project:profile",
        type="user_trait",
        importance=0.9,
        confidence=0.95,
        source_strength="user_behavior",
        metadata={"kind": "profile_evidence"},
    )
    app.memory.write(
        summary="Prefer compact answers.",
        scope="project:profile",
        type="preference",
        importance=0.8,
        confidence=0.95,
        source_strength="explicit_user",
        metadata={"profile_key": "collaboration.compact"},
    )
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call(
        "context.get",
        {
            "session_id": sid,
            "query": "ordinary project question",
            "scope": "project:profile",
            "caller_session_id": "codexsess_profile_evidence",
            "profile_limit": 3,
        },
    )
    assert ctx["profile_hints"] == [
        {
            "profile_key": "collaboration.compact",
            "hint": "Prefer compact answers.",
            "updated_at_ms": ctx["profile_hints"][0]["updated_at_ms"],
        }
    ]


def test_context_get_profile_hints_are_query_relevant(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.memory.write(
        summary="For A7S hardware bring-up, prefer UART-first checks and power evidence.",
        scope="project:profile",
        type="preference",
        importance=0.8,
        confidence=0.95,
        source_strength="explicit_user",
        metadata={"profile_key": "hardware.a7s"},
    )
    app.memory.write(
        summary="For study-note workflows, put formulas and derivations in tmp.md.",
        scope="project:profile",
        type="preference",
        importance=0.8,
        confidence=0.95,
        source_strength="explicit_user",
        metadata={"profile_key": "study.tmp"},
    )
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call(
        "context.get",
        {
            "session_id": sid,
            "query": "A7S UART power bring-up",
            "scope": "project:profile",
            "caller_session_id": "codexsess_profile_relevance",
            "profile_limit": 1,
        },
    )
    assert ctx["profile_hints"][0]["profile_key"] == "hardware.a7s"


def test_context_get_profile_hints_use_scope_fallback(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.memory.write(
        summary="For Advanced Agent work, avoid markdown memory side effects.",
        scope="advanced_agent",
        type="workflow_habit",
        importance=0.85,
        confidence=0.95,
        source_strength="explicit_user",
        metadata={"profile_key": "advanced_agent.memory_boundary"},
    )
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call(
        "context.get",
        {
            "session_id": sid,
            "query": "advanced_agent memory markdown side effects",
            "scope": "project:advanced_agent",
            "caller_session_id": "codexsess_profile_fallback",
        },
    )
    assert ctx["profile_hints"][0]["profile_key"] == "advanced_agent.memory_boundary"


def test_context_builder_injects_profile_hints_separately_from_memories(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.memory.write(
        summary="For Advanced Agent work, avoid markdown memory side effects.",
        scope="project:advanced_agent",
        type="workflow_habit",
        importance=0.85,
        confidence=0.95,
        source_strength="explicit_user",
        metadata={"profile_key": "advanced_agent.memory_boundary"},
    )
    built = app.context_builder.build_for_main(sid, "advanced_agent markdown memory", scope="project:advanced_agent")
    assert [hint.profile_key for hint in built.profile_hints] == ["advanced_agent.memory_boundary"]
    assert all(hit.type not in {"user_trait", "preference", "workflow_habit"} for hit in built.retrieved_memories)


def test_memory_search_supports_query_profile_and_keyword_labels(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.memory.write(summary="统一向量库按 LLM keywords 处理记忆分类", scope="project:facet", type="decision")
    bridge = RuntimeToolBridge(app)
    found = bridge.call("memory.search", {"query": "记忆分类 keywords", "scope": "project:facet", "query_profile": "methodology", "top_k": 3})
    assert found["ok"]
    assert found["hits"]
    labels = found["hits"][0].get("labels", {})
    assert "keywords" in labels
    assert "semantic" in labels


def test_memory_facets_are_compact_keywords_first(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    bridge = RuntimeToolBridge(app)
    bridge.call(
        "memory.write",
        {
            "summary": "codexx wrapper bootstrap hybrid memory design",
            "content": "workstream topics do not always map to folders; free keywords like codexx, sqlite-vec, FTS5, ring-buffer should remain searchable.",
            "scope": "topic:agent-runtime",
            "type": "decision",
        },
    )
    found = bridge.call("memory.search", {"query": "sqlite-vec FTS5 ring-buffer", "scope": "topic:agent-runtime", "top_k": 3})
    assert found["ok"] and found["hits"]
    labels = found["hits"][0]["labels"]
    assert set(labels).issubset({"semantic", "keywords", "workspace"})
    assert "keywords" in labels
    assert "workstream" not in labels
    assert "project" not in labels
    assert "sqlite-vec" in labels["keywords"] or "fts5" in labels["keywords"]


def test_runtime_tool_bridge_raw_tail_is_bounded(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    for i in range(5):
        app.start_user_request(sid, f"raw message {i}")
    bridge = RuntimeToolBridge(app)
    tail = bridge.call("session.raw_tail", {"session_id": sid, "limit": 3, "max_chars": 20})
    assert tail["ok"]
    assert len(tail["lines"]) == 3
    assert any("raw message 4" in line for line in tail["lines"])
    assert all("raw message 0" not in line for line in tail["lines"])


def test_workdir_chdir_updates_runtime_cwd(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    target = tmp_path / "work"
    target.mkdir()
    bridge = RuntimeToolBridge(app)
    changed = bridge.call("workdir.chdir", {"path": str(target)})
    assert changed["ok"]
    info = bridge.call("project.info")
    assert info["ok"]
    assert info["data"]["cwd"] == str(target.resolve())


def test_workspace_can_sync_process_cwd(tmp_path, monkeypatch) -> None:
    from advanced_agent.workspace import WorkspaceState

    start = tmp_path / "start"
    target = tmp_path / "target"
    start.mkdir()
    target.mkdir()
    monkeypatch.chdir(start)
    workspace = WorkspaceState(start, sync_process_cwd=True)
    workspace.chdir(target)
    assert Path.cwd() == target.resolve()


def test_runtime_tool_bridge_internal_memory_cleanup_tools(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    bridge = RuntimeToolBridge(app)
    written = app.memory.write(summary="cleanup target", scope="project:cleanup", type="note")
    assert app.memory.deactivate(written.memory_id, status="deleted")
    archived = bridge.call("memory.archive_inactive_indexes", {"limit": 5})
    assert archived["ok"] and archived["archived"] == 1
    app.db.execute("UPDATE memory_items SET status='deleted', updated_at_ms=? WHERE id=?", (app.time.wall_ms(), written.memory_id))
    purged = bridge.call("memory.purge_deleted", {"older_than_ms": app.time.wall_ms() + 1, "limit": 5})
    assert purged["ok"] and purged["purged"] == 1
