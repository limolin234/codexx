# Plugin Hooks

The core architecture is frozen around supervisor/main/interactive/audit/task/memory separation. External integrations should be plugins, not core features.

## Principle

Plugins can register hooks. The core only schedules and fires hooks. Plugin agents decide how to read external data and write outputs.

```text
plugin.json
  -> PluginRegistry
  -> HookStore
  -> AutomationEngine.tick
  -> plugin.hook.requested event
  -> plugin-specific agent/worker handles it
```

## Manifest

A plugin lives under `plugins/<name>/plugin.json`:

```json
{
  "name": "group_summary",
  "version": "0.1.0",
  "hooks": [
    {
      "kind": "plugin.group_summary.daily",
      "target": "plugin:group_summary",
      "default_delay_ms": 0,
      "repeat_ms": 86400000,
      "payload": {"summary_scope": "group"}
    }
  ]
}
```

## Hook event

When a plugin hook fires, the runtime emits:

```text
plugin.hook.requested
```

The event payload contains hook id, kind, target, and plugin payload. External plugin agents may then inspect files/APIs and write their own artifacts.
