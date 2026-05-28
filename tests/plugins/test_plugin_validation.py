from advanced_agent.plugins import PluginRegistry, PluginValidationError


def write_plugin(root, name, body):
    d = root / name
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(body)
    return d


def test_plugin_rejects_hook_outside_namespace(tmp_path) -> None:
    write_plugin(tmp_path, "bad", '''{
      "name": "bad",
      "hooks": [{"kind": "plugin.other.run", "target": "plugin:bad"}]
    }''')
    registry = PluginRegistry(tmp_path)
    try:
        registry.load()
    except PluginValidationError as exc:
        assert "must start" in str(exc)
    else:
        raise AssertionError("invalid plugin namespace should fail")


def test_plugin_rejects_non_plugin_target(tmp_path) -> None:
    write_plugin(tmp_path, "bad", '''{
      "name": "bad",
      "hooks": [{"kind": "plugin.bad.run", "target": "core:supervisor"}]
    }''')
    registry = PluginRegistry(tmp_path)
    try:
        registry.load()
    except PluginValidationError as exc:
        assert "target" in str(exc)
    else:
        raise AssertionError("invalid plugin target should fail")


def test_plugin_rejects_too_fast_repeat(tmp_path) -> None:
    write_plugin(tmp_path, "bad", '''{
      "name": "bad",
      "hooks": [{"kind": "plugin.bad.run", "target": "plugin:bad", "repeat_ms": 10}]
    }''')
    registry = PluginRegistry(tmp_path)
    try:
        registry.load()
    except PluginValidationError as exc:
        assert "repeat_ms" in str(exc)
    else:
        raise AssertionError("too fast repeat should fail")
