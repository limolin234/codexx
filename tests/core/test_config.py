import json

from advanced_agent.config import RuntimeConfig


def test_runtime_config_json_roles(tmp_path) -> None:
    path = tmp_path / "env.json"
    path.write_text(json.dumps({
        "roles": {"interactive_model": "fast", "codex_model": "default"},
        "models": {
            "fast": {
                "provider": "openai_compatible",
                "model": "m-fast",
                "base_url": "http://localhost:1234/v1",
                "api_key": "k",
            }
        },
    }))
    cfg = RuntimeConfig.load(path)
    assert cfg.model_for_role("interactive_model").model == "m-fast"
    assert cfg.model_for_role("codex_model") is None
