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
    ctx = bridge.call("context.get", {"session_id": sid, "query": "context memory", "scope": "project:ctx", "mode": "full"})
    assert ctx["ok"]
    assert any("context hello" in line for line in ctx["recent"])
    assert ctx["memories"]


def test_runtime_tool_bridge_context_get_supplement_skips_live_recent(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("supplement")
    for i in range(6):
        app.start_user_request(sid, f"turn {i}")
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call("context.get", {"session_id": sid, "query": "turn", "mode": "supplement", "live_recent_limit": 2, "recent_limit": 10})
    assert ctx["ok"]
    assert ctx["mode"] == "supplement"
    assert ctx["live_recent_skipped"] == 2
    assert any("turn 3" in line for line in ctx["recent"])
    assert all("turn 4" not in line and "turn 5" not in line for line in ctx["recent"])


def test_runtime_tool_bridge_context_get_excludes_noisy_logs_by_default(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    app.memory.write(summary="noisy terminal log memory", scope="project:ctx", type="codex_interactive_log", importance=0.9)
    app.memory.write(summary="clean design decision memory", scope="project:ctx", type="decision", importance=0.8)
    bridge = RuntimeToolBridge(app)
    ctx = bridge.call("context.get", {"query": "memory", "scope": "project:ctx", "memory_top_k": 5})
    assert ctx["ok"]
    assert "codex_interactive_log" in ctx["excluded_memory_types"]
    assert all(item["type"] != "codex_interactive_log" for item in ctx["memories"])
    assert any(item["type"] == "decision" for item in ctx["memories"])

    with_logs = bridge.call("context.get", {"query": "memory", "scope": "project:ctx", "memory_top_k": 5, "include_log_memories": True})
    assert any(item["type"] == "codex_interactive_log" for item in with_logs["memories"])


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
