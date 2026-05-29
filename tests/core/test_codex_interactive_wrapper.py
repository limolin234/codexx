from pathlib import Path

from advanced_agent.codex_interactive import DEFAULT_BOOTSTRAP_CHARS, _clean_terminal_log, _ingest_codex_log_tail, _resolve_runtime_path, build_bootstrap_prompt, build_codex_env, build_combined_model_instructions, codex_mcp_config_args, should_inject_bootstrap
from advanced_agent.runtime.app import RuntimeApp


def test_codex_interactive_env_contains_runtime_handles(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    env = build_codex_env(app, sid, str(tmp_path / "state.sqlite"), tmp_path / "codex.log")
    assert env["ADVANCED_AGENT_SESSION"] == sid
    assert env["ADVANCED_AGENT_DB"].endswith("state.sqlite")
    assert env["ADVANCED_AGENT_CODEX_LOG"].endswith("codex.log")


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


def test_ingest_codex_log_tail_cleans_and_marks_interrupt(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.start_user_request(sid, "closing buffer should be preserved")
    log_path = tmp_path / "codex.log"
    log_path.write_text("\x1b[31mworking\x1b[0m\n[WRAPPER_CTRL_C_INTERRUPTED]\n", encoding="utf-8")
    _ingest_codex_log_tail(app, sid, "codexsess_test", log_path)
    records = app.memory.recent(scope="project:advanced_agent", limit=3)
    assert records
    assert any("interrupted and saved" in record.summary for record in records)
    assert all("\x1b" not in (record.content or "") for record in records)
    assert any(record.type == "handoff" and "closing buffer" in (record.content or "") for record in records)


def test_build_bootstrap_prompt_includes_bounded_recent_tail(tmp_path) -> None:
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    sid = app.default_session()
    app.start_user_request(sid, "short first message")
    app.start_user_request(sid, "important latest wrapper context")
    prompt = build_bootstrap_prompt(app, sid, max_chars=200)
    assert "Advanced Agent bootstrap context" in prompt
    assert "session_raw_tail" in prompt
    assert "context_get" in prompt
    assert "important latest wrapper context" in prompt
    assert len(prompt) < 2000




def test_default_bootstrap_is_quiet_and_raw_tail_is_opt_in() -> None:
    assert DEFAULT_BOOTSTRAP_CHARS == 0


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
