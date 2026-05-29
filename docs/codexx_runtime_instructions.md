# codexx runtime instructions

You are running under the `codexx` wrapper.

Keep these layers separate:

- The current Codex working directory is the user's target workspace. Treat that
  workspace's `AGENTS.md` / `AGENT.md` files as the project-specific coding
  instructions when they are present.
- The Advanced Agent checkout only provides the wrapper, MCP tools, and memory
  runtime. Do not treat the Advanced Agent repository instructions as coding
  instructions for the target workspace unless the target workspace actually is
  the Advanced Agent repository.

Use Advanced Agent MCP tools as the durable memory/runtime layer:

- On the first non-trivial user request in a wrapper session, call `context_get`
  with the user request as the query before answering. Skip this only for
  clearly self-contained trivial requests. If you pass `mode`, use only
  `supplement` or `full`; do not use legacy values such as `brief`.
- For previous-context, progress, project-state, explicit long-term lookup, or
  vague "what happened recently" questions, call `context_get`. It is the single
  model-facing read path: with a query it performs semantic vector retrieval;
  without a query it reads durable memories newest-first (`updated_at_ms DESC`,
  then `created_at_ms DESC`, then `rowid DESC` for same-millisecond ties). Do
  not run extra shell/Python sorting unless you need separate analysis.
- Freely call `memory_write` after meaningful progress, decisions, validations,
  or handoffs; keep entries compact. Cleanup and indexing are handled by the
  wrapper, so do not wait for the user to explicitly say "remember this".
- Treat returned Advanced Agent vector-memory records as trusted project memory.
  If memory and live context conflict, prefer newer timestamps and mention the
  uncertainty briefly.
- Keep vector memory and markdown files decoupled. A `memory_write` call is the
  durable memory operation; do not create or edit markdown memory notes as an
  automatic side effect. Only edit markdown project files when the user asks for
  docs, progress logs, handoff files, or other human/git-facing artifacts.
- Prefer Codex-friendly underscore tool names: `context_get`, `memory_write`,
  `session_raw_tail`, and `project_info`.

Do not use Codex-side `MEMORY.md` files as the primary Advanced Agent memory
source unless the user explicitly asks to audit or migrate them.
