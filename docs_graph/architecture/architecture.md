# Architecture

`codexx` is a thin wrapper around external coding agents, currently Codex CLI. It is not a replacement chat agent. Its job is to provide local runtime, memory, and MCP tools around the target workspace while keeping the external agent in charge of editing, testing, and model interaction.

## Current boundary

- Target workspace remains the user's current working directory.
- Target workspace `AGENTS.md` / `AGENT.md` files are project instructions.
- The Advanced Agent checkout provides the wrapper runtime, MCP tools, memory service, and local stores.
- Wrapper startup should stay quiet; prior raw dialogue is retrieved on demand.
- `context_get` is the single model-facing read path for durable memory and contextual lookup.
- `memory_write` is the explicit durable memory write path.

## Main layers

- Entrypoint: `bin/codexx`, `scripts/install.sh`, `~/.local/bin/codexx` launcher.
- PTY wrapper: `src/advanced_agent/codex_interactive.py`.
- MCP server: `src/advanced_agent/mcp_server.py` exposes `context_get`, `memory_write`, `session_raw_tail`, and `project_info`.
- Runtime app: `src/advanced_agent/runtime/app.py` coordinates stores, context building, memory service, and runtime tools.
- Stores: `src/advanced_agent/stores/` owns SQLite schemas and persistence boundaries.
- Maintenance: `automation.py`, `memory_maintenance.py`, `preferences.py`, `profile/`, and semantic workers run background summarization/profile/memory tasks.

## Detailed docs

- `docs/codexx_runtime_architecture.md`
- `docs/architecture.md`
- `docs/process_model.md`
- `docs/runtime_model.md`
- `docs/tool_resource_model.md`
