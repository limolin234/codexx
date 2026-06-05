# codexx docs graph

This directory is the repo-local docs graph for `codexx` / Advanced Agent.

Use it as the short, path-addressable entry layer for agent-readable project context. The older `docs/` directory remains the detailed document archive; docs graph files should summarize current boundaries and link to detailed docs instead of duplicating them.

## Reading order

For most project work, read only the smallest relevant path:

- `architecture/architecture.md` - current system boundary and module map
- `runtime/runtime.md` - runtime process model, SQLite state, hooks, and daemon
- `memory/memory.md` - durable memory, raw tail, semantic summaries, and profile hints
- `codex/codex.md` - `codexx` wrapper and MCP bridge into Codex
- `plugins/plugins.md` - plugin and hook extension surface
- `testing/testing.md` - validation commands and test layout
- `operations/operations.md` - install, generated files, cleanup, and local system footprint

## Rules

- Keep docs graph files concise and current.
- Put stable project knowledge here: decisions, invariants, module boundaries, commands, and handoffs.
- Link to detailed `docs/*.md` files for deeper background.
- Do not use this directory as a raw transcript dump.
- If a file grows too large, split by module or concern.
