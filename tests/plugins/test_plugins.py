from advanced_agent.plugins import PluginRegistry
from advanced_agent.runtime.app import RuntimeApp


def test_plugin_registry_schedules_custom_hook(tmp_path) -> None:
    plugin_dir = tmp_path / "plugins"
    plugin = plugin_dir / "sample"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text('''{
      "name": "sample",
      "version": "0.1.0",
      "hooks": [{"kind": "plugin.sample.run", "target": "plugin:sample", "default_delay_ms": 0, "payload": {"x": 1}}]
    }''')
    app = RuntimeApp.create(tmp_path / "state.sqlite")
    registry = PluginRegistry(plugin_dir)
    registry.load()
    ids = registry.schedule_default_hooks(app.hooks, app.time)
    assert ids
    result = app.automation.tick()
    assert any(action.startswith("plugin_hook_requested") for action in result.actions)
    events = app.events.store.recent(20)
    assert any(event.type == "plugin.hook.requested" for event in events)
