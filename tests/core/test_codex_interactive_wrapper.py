import os
from pathlib import Path

from advanced_agent.codex_interactive import DEFAULT_BOOTSTRAP_CHARS, DEFAULT_CODEX_LOG_SESSION_RETENTION, _BoundedCleanTerminalLog, _append_codex_log_tail_to_ring_buffer, _append_codex_tail_to_ring_buffer, _clean_terminal_log, _prune_codex_interactive_logs, _record_semantic_event, _resolve_runtime_path, build_bootstrap_prompt, build_codex_env, build_combined_model_instructions, codex_mcp_config_args, should_inject_bootstrap, startup_status_line
from advanced_agent.runtime.background import BackgroundRuntimeConfig
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.terminal_semantics import GenericTtyInputTracker, SemanticChunk, SemanticRingBuffer


def test_codex_interactive_env_contains_runtime_handles(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    env = build_codex_env(app, sid, str(tmp_path / "state.sqlite"), tmp_path / "codex.log")
    assert env["ADVANCED_AGENT_SESSION"] == sid
    assert env["ADVANCED_AGENT_DB"].endswith("state.sqlite")
    assert env["ADVANCED_AGENT_CODEX_LOG"].endswith("codex.log")


def test_startup_status_line_reports_memory_key_readiness(tmp_path) -> None:
    config = tmp_path / ".env.json"
    config.write_text(
        """
{
  "roles": {"memory_model": "small", "memory_write_model": "strong"},
  "models": {
    "small": {"provider": "openai_compatible", "model": "s", "base_url": "http://x/v1", "api_key": "ks"},
    "strong": {"provider": "openai_compatible", "model": "b", "base_url": "http://x/v1", "api_key": "kb"}
  }
}
""",
        encoding="utf-8",
    )
    line = startup_status_line(config, background_config=BackgroundRuntimeConfig(enabled=True))
    assert "memory_model=可用" in line
    assert "memory_write_model=可用" in line
    assert "自动画像管理=已启动" in line


def test_startup_status_line_treats_missing_model_keys_as_optional(tmp_path) -> None:
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
    line = startup_status_line(config, background_config=BackgroundRuntimeConfig(enabled=True))
    assert "memory_model=未配置(可选)" in line
    assert "memory_write_model=未配置(可选)" in line
    assert "自动画像管理=本地降级" in line


def test_codex_mcp_config_args_inject_project_server(tmp_path) -> None:
    project_root = tmp_path / "advanced_agent"
    launch_cwd = tmp_path / "caller"
    project_root.mkdir()
    launch_cwd.mkdir()
    args = codex_mcp_config_args(str(tmp_path / "state.sqlite"), str(tmp_path / ".env.json"), project_root=project_root, launch_cwd=launch_cwd)
    joined = " ".join(args)
    assert "mcp_servers.advanced-agent.command" in joined
    assert "advanced_agent.mcp_server" in joined
    assert str(tmp_path / "state.sqlite") in joined
    assert f'PYTHONPATH="{project_root / "src"}"' in joined
    assert f'ADVANCED_AGENT_LAUNCH_CWD="{launch_cwd}"' in joined
    assert f'mcp_servers.advanced-agent.cwd="{launch_cwd}"' in joined


def test_codex_env_separates_project_root_from_launch_cwd(tmp_path, monkeypatch) -> None:
    launch_cwd = tmp_path / "caller"
    project_root = tmp_path / "advanced_agent"
    launch_cwd.mkdir()
    project_root.mkdir()
    monkeypatch.chdir(launch_cwd)
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    env = build_codex_env(app, sid, str(tmp_path / "state.sqlite"), tmp_path / "codex.log", project_root=project_root)
    assert env["ADVANCED_AGENT_ROOT"] == str(project_root)
    assert env["ADVANCED_AGENT_PROJECT_ROOT"] == str(project_root)
    assert env["ADVANCED_AGENT_LAUNCH_CWD"] == str(launch_cwd)


def test_relative_runtime_paths_resolve_under_project_root(tmp_path) -> None:
    project_root = tmp_path / "advanced_agent"
    assert _resolve_runtime_path("runtime/advanced_agent.sqlite", project_root) == project_root / "runtime/advanced_agent.sqlite"
    assert _resolve_runtime_path(tmp_path / "custom.sqlite", project_root) == tmp_path / "custom.sqlite"


def test_clean_terminal_log_removes_ansi_noise() -> None:
    cleaned = _clean_terminal_log("\x1b[31mhello\x1b[0m\r\n\x1b]0;title\x07world")
    assert "hello" in cleaned
    assert "world" in cleaned
    assert "\x1b" not in cleaned


def test_clean_terminal_log_treats_carriage_return_as_overwrite() -> None:
    cleaned = _clean_terminal_log("progress 1%\rprogress 2%\rprogress 3%")
    assert "progress 3%" in cleaned
    assert "progress 1%" not in cleaned


def test_generic_tty_input_tracker_extracts_user_submit() -> None:
    tracker = GenericTtyInputTracker()
    chunks = tracker.observe("默认写到 tmp.md".encode("utf-8") + b"\r")
    assert len(chunks) == 1
    assert chunks[0].kind == "user_submit"
    assert chunks[0].text == "默认写到 tmp.md"


def test_bounded_clean_terminal_log_writes_clean_capped_transcript(tmp_path) -> None:
    log_path = tmp_path / "codexsess_test.terminal.log"
    with _BoundedCleanTerminalLog(log_path, max_bytes=200) as log:
        log.write(("\x1b[31mfirst noisy line\x1b[0m\n" + "x" * 300).encode())
        log.write(b"\n[USER_INPUT_BYTES]\n")
        log.write("\x1b[32m用户偏好：保留清洗后的日志\x1b[0m\n".encode())

    text = log_path.read_text(encoding="utf-8")
    assert "\x1b" not in text
    assert "[USER_INPUT_BYTES]" not in text
    assert len(log_path.read_bytes()) <= 200
    assert "用户偏好" in text


def test_semantic_event_record_schedules_after_three_user_submits(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    ring = SemanticRingBuffer()
    for idx in range(3):
        _record_semantic_event(app, sid, ring, SemanticChunk(kind="user_submit", text=f"message {idx}"), schedule_reason="user_submit")
    assert app.semantic_store.unconsumed_user_submits(sid) == 3
    due = app.hooks.due(app.time.wall_ms(), limit=5)
    assert any(hook.kind == "semantic_maintenance" and hook.payload["reason"] == "user_submit_3" for hook in due)


def test_codex_log_tail_buffers_raw_tail_without_durable_memory(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.record_user_message(sid, "closing buffer should be preserved")
    log_path = tmp_path / "codex.log"
    log_path.write_text("\x1b[31mworking\x1b[0m\n[WRAPPER_CTRL_C_INTERRUPTED]\n", encoding="utf-8")
    _append_codex_log_tail_to_ring_buffer(app, sid, "codexsess_test", log_path)
    records = app.memory.recent(scope="project:advanced_agent", limit=5)
    assert all(record.type != "codex_interactive_log" for record in records)
    assert all("Codex wrapper closing ring-buffer handoff" not in record.summary for record in records)
    raw_tail = app.sessions.raw_tail_lines(sid, limit=5, max_chars=300)
    assert any("message/codex_tail" in line and "working" in line for line in raw_tail)
    events = app.events.store.recent(5)
    assert any(event.type == "codex.interactive.tail_buffered" for event in events)


def test_append_codex_tail_to_ring_buffer_is_idempotent(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    _append_codex_tail_to_ring_buffer(app, sid, "codexsess_test", "latest terminal cache")
    _append_codex_tail_to_ring_buffer(app, sid, "codexsess_test", "latest terminal cache")
    lines = app.sessions.raw_tail_lines(sid, limit=10, max_chars=200)
    assert sum("message/codex_tail" in line and "latest terminal cache" in line for line in lines) == 1


def test_build_bootstrap_prompt_includes_bounded_recent_tail(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.record_user_message(sid, "short first message")
    app.record_user_message(sid, "important latest wrapper context")
    prompt = build_bootstrap_prompt(app, sid, max_chars=200)
    assert "Advanced Agent bootstrap context" in prompt
    assert "session_raw_tail" in prompt
    assert "context_get" in prompt
    assert "important latest wrapper context" in prompt
    assert len(prompt) < 2000




def test_default_bootstrap_is_quiet_and_raw_tail_is_opt_in() -> None:
    assert DEFAULT_BOOTSTRAP_CHARS == 0


def test_prune_codex_interactive_logs_keeps_newest_sessions(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    log_root = tmp_path / "codex_interactive"
    log_root.mkdir()
    for i in range(35):
        sid = f"codexsess_{i:02d}"
        for suffix in (".terminal.log", ".instructions.md"):
            path = log_root / f"{sid}{suffix}"
            path.write_text(sid, encoding="utf-8")
            ts = 1_700_000_000 + i
            os.utime(path, (ts, ts))
    unrelated = log_root / "README.txt"
    unrelated.write_text("keep me", encoding="utf-8")

    deleted = _prune_codex_interactive_logs(app, log_root, keep_sessions=DEFAULT_CODEX_LOG_SESSION_RETENTION)

    assert deleted == 6
    remaining_sessions = {
        path.name.split(".")[0]
        for path in log_root.glob("codexsess_*.*")
    }
    assert len(remaining_sessions) == DEFAULT_CODEX_LOG_SESSION_RETENTION
    assert "codexsess_00" not in remaining_sessions
    assert "codexsess_01" not in remaining_sessions
    assert "codexsess_02" not in remaining_sessions
    assert "codexsess_03" in remaining_sessions
    assert unrelated.exists()
    events = app.events.store.recent(5)
    assert any(event.type == "codex.interactive.logs_pruned" for event in events)


def test_combined_model_instructions_preserve_user_and_add_codexx_contract(tmp_path) -> None:
    project_root = tmp_path / "advanced_agent"
    docs = project_root / "docs"
    docs.mkdir(parents=True)
    (docs / "codexx_runtime_instructions.md").write_text("Use context_get from wrapper memory.", encoding="utf-8")
    user_file = tmp_path / "user_instructions.md"
    user_file.write_text("Keep answers concise.", encoding="utf-8")

    out = build_combined_model_instructions(
        tmp_path / "runtime" / "combined.md",
        project_root=project_root,
        user_instructions_path=user_file,
    )

    text = out.read_text(encoding="utf-8")
    assert "Keep answers concise." in text
    assert "Use context_get from wrapper memory." in text
    assert text.index("Keep answers concise.") < text.index("Use context_get")

def test_should_inject_bootstrap_only_without_explicit_prompt_or_subcommand() -> None:
    assert should_inject_bootstrap([])
    assert should_inject_bootstrap(["--model", "gpt-5.4"])
    assert should_inject_bootstrap(["--cd", "/tmp", "--search"])
    assert not should_inject_bootstrap(["continue this exact prompt"])
    assert not should_inject_bootstrap(["exec", "echo hi"])
    assert not should_inject_bootstrap(["resume", "--last"])


def test_codex_close_enqueues_memory_maintenance(tmp_path) -> None:
    from advanced_agent.codex_interactive import _enqueue_codex_close_maintenance, _record_codex_close_event
    from advanced_agent.runtime.app import RuntimeApp

    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.create_session("codex-close")
    log_path = tmp_path / "codex.log"
    _record_codex_close_event(app, sid, "codexsess_test", log_path, 0)
    _enqueue_codex_close_maintenance(app, sid, "codexsess_test", log_path, 0)
    events = app.events.store.recent(5)
    assert any(event.type == "codex.interactive.closed" for event in events)
    due = app.hooks.due(app.time.wall_ms(), limit=5)
    assert any(hook.kind == "memory_maintenance" and hook.payload["codex_session_id"] == "codexsess_test" for hook in due)
