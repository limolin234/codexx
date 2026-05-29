# MCP Runtime Bridge

## MCP vs toolcall

- **Toolcall** is the model-facing action format. The model emits a structured
  call such as `memory_search({query: ...})`.
- **MCP** is a tool-provider protocol. An MCP server exposes tools/resources;
  a client such as Codex can discover those tools and convert them into the
  model's tool schemas.

In short:

```text
MCP server exposes tools
  -> Codex/MCP client presents them to the model as tool schemas
  -> model emits toolcall
  -> client invokes MCP tool
  -> tool result returns to model
```

Advanced Agent should be a local project-level MCP/tool provider, not a global
skill. Codex remains the coding agent; Advanced Agent provides long-lived memory,
session, task, hook, and event state.

## First project-level tools

- `memory.search`
- `memory.write`
- `memory.recent`
- `context.get`
- `session.recent`
- `task.list`
- `task.state`
- `task.tail`
- `project.info`
- `timer.schedule`
- `event.wait`

## Timer and wait semantics

Models should not literally sleep for a long time. A timer tool should schedule a
runtime hook and return a handle:

```text
timer.schedule(delay_ms, reason, target)
  -> hook_id
```

`event.wait` should be bounded. For long waits, it returns a pending handle or an
empty result instead of blocking the runtime forever:

```text
event.wait(type, timeout_ms, filters)
  -> event | timeout
```

This lets Codex/main ask the runtime to pause/wake/check without inventing time in
text.

## Context maintenance mode

There are two context paths:

1. **Automatic injection inside Advanced Agent runtime**: before main answers, the
   runtime should inject bounded recent context and retrieved vector memories.
   The model should not have to remember to call memory for every normal turn.
2. **On-demand MCP tools for Codex/external agents**: external agents cannot be
   force-fed our private context unless their client supports resources/context
   injection. For them, expose `context.get(query, session_id)` and instruct the
   agent to call it at the start of context-dependent tasks.

`context.get` defaults to `mode="supplement"` for Codex/external agents. The
MCP schema exposes the complete mode enum: `supplement` and `full` only; do
not use older names such as `brief`. In supplement mode it assumes the
caller already has the live recent dialogue in its own model context, skips
that tail, and only returns older supplemental session lines plus vector
memories. `mode="full"` is still available for debugging or internal
callers that need the complete bounded view.

`context.get` returns:

- supplemental prior user-visible session lines in `recent` /
  `supplemental_recent`;
- vector memory hits for the query;
- a short instruction telling the model to use the context or call more specific
  tools.

Routine memory writes are exposed with non-destructive/idempotent MCP tool
annotations, so clients that honor annotations can auto-approve `memory_write`
style note/decision/handoff records without treating them like filesystem or
process mutations.

To avoid overlap with Codex's own live context and reduce token waste, default
supplement retrieval excludes `codex_interactive_log` memories. Those logs are
kept for audit/debug recovery, but they are noisy and often duplicate what Codex
already saw. Callers can opt in with `include_log_memories=true` when debugging
the wrapper itself.

This avoids relying only on vague prompts like "remember to search memory", while
still keeping MCP compatible with normal toolcall flow and reducing duplicate
token injection.

## Current implementation

Implemented stdio MCP entrypoint:

```bash
PYTHONPATH=src .venv/bin/python -m advanced_agent.mcp_server \
  --db runtime/advanced_agent.sqlite \
  --config .env.json
```

Codex registration example:

```bash
codex mcp add advanced-agent --env PYTHONPATH=src -- \
  .venv/bin/python -m advanced_agent.mcp_server \
  --db runtime/advanced_agent.sqlite \
  --config .env.json
```

`memory.write`, `memory.search`, and `context.get` now go through
`MemoryService`/`MemoryIndexer`, so records are actually inserted into SQLite,
tagged/aligned, vector-indexed by sqlite-vec, and hydrated back to tool callers.
