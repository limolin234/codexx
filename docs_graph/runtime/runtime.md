# Runtime

Runtime state is local SQLite-backed infrastructure around wrapped agent sessions. It should stay separate from target project source files except for explicit user edits made by Codex.

## Process model

- `codexx` launches Codex in a PTY from the caller's target workspace.
- The wrapper injects runtime instructions and an MCP server using temporary Codex configuration, without requiring global Codex config edits.
- Runtime tools operate through the project-local MCP server.
- Background maintenance is queued and bounded; expensive major memory writes should happen at explicit wrapper-close or manual paths, not on every small event.

## Storage split

Current design separates runtime and memory sidecars:

- `runtime/advanced_agent.sqlite` - sessions, runtime events, hooks, semantic state, tasks, and operational queues.
- `memory/longterm.sqlite` - durable memory records and retrieval metadata.
- `memory/rawtail.sqlite` - bounded raw terminal/dialogue tail for on-demand inspection.

WAL sidecars may exist while live. Do not assume copying only a live `.sqlite` file captures all recent writes; snapshot/export or use SQLite backup when migrating.

## Detailed docs

- `docs/runtime_model.md`
- `docs/sqlite_schema.md`
- `docs/memory_directory.md`
- `docs/session_lifecycle.md`
- `docs/long_running_tasks.md`
- `docs/workdir_control.md`
