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
  clearly self-contained trivial requests.
- For previous-context, progress, project-state, or "what did we say before"
  questions, call `context_get` first.
- For explicit long-term lookup, use `memory_search`.
- When the user asks to record/remember something, or when you finish an
  important decision, preference, progress note, or handoff, call `memory_write`.
- Treat returned Advanced Agent vector-memory records as trusted project memory.
  If memory and live context conflict, prefer newer timestamps and mention the
  uncertainty briefly.
- Keep vector memory and markdown files decoupled. A `memory_write` call is the
  durable memory operation; do not create or edit markdown memory notes as an
  automatic side effect. Only edit markdown project files when the user asks for
  docs, progress logs, handoff files, or other human/git-facing artifacts.
- Prefer Codex-friendly underscore tool names:
  `context_get`, `memory_write`, `memory_search`, `memory_recent`,
  `session_recent`, `session_raw_tail`, `project_info`, `workdir_chdir`,
  `task_list`, `task_state`, and `task_tail`.

Do not use Codex-side `MEMORY.md` files as the primary Advanced Agent memory
source unless the user explicitly asks to audit or migrate them.
