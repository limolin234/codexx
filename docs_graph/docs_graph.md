# codexx docs graph

This directory is the repo-local docs graph for `codexx` / Advanced Agent.

Use it as the short, path-addressable entry layer for agent-readable project context. Detailed project documentation has been migrated into this tree; concise entry files summarize current boundaries and link to deeper sibling documents.

## Reading order

For most project work, read only the smallest relevant path:

- `architecture/architecture.md` - current system boundary and module map
- `runtime/runtime.md` - runtime process model, SQLite state, hooks, and daemon
- `memory/memory.md` - durable memory, raw tail, semantic summaries, and profile hints
- `codex/codex.md` - `codexx` wrapper and MCP bridge into Codex
- `context/context.md` - context selection, compaction, forking, and prompt building
- `plugins/plugins.md` - plugin and hook extension surface
- `testing/testing.md` - validation commands and test layout
- `operations/operations.md` - install, generated files, cleanup, and local system footprint
- `roadmap/roadmap.md` - roadmap entry and phase planning

## Rules

- Keep docs graph files concise and current.
- Put stable project knowledge here: decisions, invariants, module boundaries, commands, and handoffs.
- Link to detailed sibling `docs_graph/**/*.md` files for deeper background.
- Do not use this directory as a raw transcript dump.
- If a file grows too large, split by module or concern.
