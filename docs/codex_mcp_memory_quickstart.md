# Codex + Advanced Agent MCP memory quickstart

This project now exposes the runtime memory/context layer as a project-local MCP
server. Codex stays interactive; Advanced Agent provides tools for memory,
context, task tails, hooks, and project info.

## Preferred entrypoint: our wrapper

Use our entrypoint instead of launching `codex` directly:

```bash
PYTHONPATH=src .venv/bin/python -m advanced_agent.codex_interactive \
  --db runtime/advanced_agent.sqlite \
  --config .env.json \
  --
```

The wrapper injects the project-local MCP server with Codex `-c` overrides, so
it does not need to mutate global `~/.codex/config.toml`.

Use `--no-mcp` only for debugging the raw Codex wrapper.

## Optional: register the MCP server globally in Codex

From the project root:

```bash
codex mcp add advanced-agent --env PYTHONPATH=src -- \
  .venv/bin/python -m advanced_agent.mcp_server \
  --db runtime/advanced_agent.sqlite \
  --config .env.json
```

Then in Codex, ask it to use the tool instead of guessing:

```text
调用 context.get 看看之前的记录，然后继续当前项目。
```

Useful first tools:

- `context_get`: recent session lines + vector memory hits.
- `memory_write`: write durable decisions, preferences, handoff notes.
- `memory_search`: search hydrated memory records, including content snippets.
- `memory_recent`: inspect recent memory when the query is vague.
- `session_recent`: inspect recent runtime dialogue lines.
- `project_info`: get cwd/project root.

Dotted aliases such as `context.get` and `memory.write` also exist for direct MCP
debugging, but Codex should prefer underscore names because they map more safely
to model tool/function names.

## Direct smoke test without Codex

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import anyio
from advanced_agent.mcp_server import create_mcp

async def main():
    mcp = create_mcp('runtime/mcp_smoke.sqlite', None)
    _, w = await mcp.call_tool('memory_write', {
        'summary': 'MCP smoke memory',
        'content': 'Codex can write memory through toolcall and search it later.',
        'scope': 'project:advanced_agent',
    })
    print(w)
    _, s = await mcp.call_tool('memory_search', {
        'query': 'toolcall search memory',
        'scope': 'project:advanced_agent',
    })
    print(s['hits'][0])

anyio.run(main)
PY
```

## Design note

MCP is only the protocol adapter. The real runtime implementation remains in
`RuntimeToolBridge` and `MemoryService`, so later HTTP/server/daemon modes can
reuse the same code path.
