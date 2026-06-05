# Plugins and hooks

Plugins and hooks are extension surfaces around the runtime. Keep project-level additions scoped so they do not burden unrelated projects.

## Current surfaces

- Plugin registry and manifests: `src/advanced_agent/plugins.py`, `plugins/`.
- Hook storage and runtime queue: `src/advanced_agent/hooks.py`, `src/advanced_agent/stores/hook_store.py`.
- Automation daemon: `src/advanced_agent/daemon.py`, `src/advanced_agent/automation.py`.
- Capability boundaries: `capabilities.py`, `capability_executor.py`, and related docs.

## Rules

- Prefer project-local plugins/skills/config when behavior is project-specific.
- Keep install/remove helpers conservative and non-destructive.
- Avoid broad global config mutations unless the user explicitly asks.

## Detailed docs

- `docs/plugin_hooks.md`
- `docs/automation_hooks.md`
- `docs/capability_router.md`
- `docs/capability_executor.md`
- `docs/long_running_tasks.md`
