# Memory

Project memory is SQLite-backed and exposed to Codex through MCP tools. Markdown docs and vector memory are separate layers: durable memory writes go through `memory_write`; human/git-facing project docs are edited only when the user asks for documentation or handoff artifacts.

## Read path

Use `context_get` for context-dependent work:

- previous progress or project state
- explicit long-term lookup
- vague questions like "what happened recently"
- ambiguous work that benefits from durable memory

With a query, `context_get` performs semantic/vector retrieval. Without a query or in recent-style calls, it reads durable memories newest-first according to store ordering.

## Write path

Use `memory_write` after meaningful project progress, decisions, validations, or handoffs.

For this project, use:

- `scope`: `project:advanced_agent`
- `type`: `decision`, `preference`, `handoff`, `note`, or `verification`
- concise searchable `summary`
- concrete `content` with files, commands, commits, validation, and next steps

## Runtime memory layers

- Durable memory: `memory/longterm.sqlite`
- Bounded raw tail: `memory/rawtail.sqlite`
- Runtime semantic state and queues: `runtime/advanced_agent.sqlite`
- Profile hints and overlays are runtime-built context, not a replacement for explicit project docs.

## Detailed docs

- `memory_design.md`
- `vector_memory.md`
- `memory_indexer.md`
- `memory_auto_injection.md`
- `preference_worker.md`
- `wrapper_auto_memory.md`
