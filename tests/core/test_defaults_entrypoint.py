from advanced_agent import defaults
from advanced_agent.codex_interactive import codex_mcp_config_args


def test_defaults_can_be_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("ADVANCED_AGENT_DB", "runtime/custom.sqlite")
    monkeypatch.setenv("ADVANCED_AGENT_CONFIG", "custom.env.json")
    assert defaults.default_db() == "runtime/custom.sqlite"
    assert defaults.default_config() == "custom.env.json"


def test_codex_mcp_config_args_include_runtime_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ADVANCED_AGENT_SCOPE", "project:test")
    args = codex_mcp_config_args(str(tmp_path / "state.sqlite"), str(tmp_path / ".env.json"), project_root=tmp_path)
    joined = " ".join(args)
    assert "ADVANCED_AGENT_DB" in joined
    assert "ADVANCED_AGENT_CONFIG" in joined
    assert "ADVANCED_AGENT_MEMORY_TRUST" in joined
    assert "project:test" in joined
