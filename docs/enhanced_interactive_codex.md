# Enhanced Interactive Codex Wrapper

`aa-codex` style interactive mode should preserve Codex's native UX while adding
Advanced Agent runtime features around it.

First implementation module:

```text
src/advanced_agent/codex_interactive.py
```

Behavior:

```text
advanced_agent wrapper
  -> resumes default Advanced Agent session
  -> starts `codex` in a PTY
  -> injects the project-local Advanced Agent MCP server with temporary Codex
     `-c mcp_servers...` overrides
  -> passes ADVANCED_AGENT_SESSION / DB / LOG env vars
  -> tees terminal bytes to runtime/codex_interactive/*.terminal.log
  -> on exit, indexes the transcript tail through MemoryIndexer
```

This does not replace Codex. It records and contextualizes Codex.

Limitations:

- PTY logs are byte streams, not structured Codex events.
- Full semantic memory should come from end-of-session summaries or explicit MCP
  `memory.write` calls, not raw terminal text alone.
- MCP protocol is configured by the wrapper by default. Use `--no-mcp` only
  when debugging raw Codex pass-through.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m advanced_agent.codex_interactive --db runtime/advanced_agent.sqlite --config .env.json --
```

This is now the preferred project entrypoint. Codex remains interactive, while
the wrapper makes tools such as `context.get`, `memory.write`, `memory.search`,
`task.*`, `timer.schedule`, and `event.wait` available without editing global
`~/.codex/config.toml`.

Codex should prefer underscore aliases (`context_get`, `memory_write`,
`memory_search`, `task_tail`, etc.) because OpenAI-style tool/function names are
more reliable without dots. Dotted MCP names are still exposed for direct debug
compatibility.
