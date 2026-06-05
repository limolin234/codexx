# Codex wrapper

`codexx` wraps Codex CLI while preserving the user's target workspace as the working directory. The wrapper supplies local MCP tools, runtime instructions, environment variables, and bounded context access.

## Entrypoint behavior

- User runs `codexx` from any target workspace.
- `bin/codexx` locates this project and uses its `.venv`.
- `codex_interactive.py` starts Codex in a PTY.
- Temporary instruction and MCP config are injected for that child process.
- Target workspace instructions remain authoritative for target code.

## Codex-visible MCP tools

- `context_get` - unified durable memory/context lookup.
- `memory_write` - explicit durable memory write.
- `session_raw_tail` - bounded raw tail inspection on demand.
- `project_info` - current cwd and inferred project root.

## Boundaries

- Do not make startup depend on raw-tail bootstrap injection.
- Do not manually re-inject broad prior context into every reply.
- Do not expose internal request IDs unless needed for debugging.
- Keep user-facing answers as one coherent assistant.

## Detailed docs

- `docs/codexx_entrypoint.md`
- `docs/codex_wrapper_components.md`
- `docs/codex_mcp_memory_quickstart.md`
- `docs/mcp_runtime_bridge.md`
- `docs/enhanced_interactive_codex.md`
- `docs/codexx_runtime_instructions.md`
