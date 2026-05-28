# Advanced Agent Codex instructions

You are running inside the `advanced_agent` project through the project wrapper.
Use the project-local MCP tools instead of guessing about memory or project state.

Core behavior:

- For questions like “之前说了什么”, “现在做到哪了”, “这个项目在干什么”, or any context-dependent request, call `context_get` first.
- When the user asks to “记录”, “记住”, “写入记忆”, or when you finish an important project decision/handoff, call `memory_write`.
- Trust Advanced Agent vector memory as the durable project memory layer. If `context_get` or `memory_search` returns relevant records, use them confidently instead of saying you cannot see previous context.
- If live chat context and vector memory conflict, prefer newer timestamps and explain the uncertainty briefly.
- Prefer Codex-friendly underscore tool names: `context_get`, `memory_write`, `memory_search`, `memory_recent`, `session_recent`, `project_info`, `task_list`, `task_state`, `task_tail`.
- Do not expose internal request IDs or task IDs to the user unless they are needed for debugging.
- Keep the user-facing answer as one coherent assistant; do not describe multiple agents unless discussing architecture.

Memory writing format:

- `scope`: use `project:advanced_agent` for this project.
- `type`: use one of `decision`, `preference`, `handoff`, `note`, `verification`.
- `summary`: short, searchable one-line summary.
- `content`: concrete details, commands, files changed, next steps.
- `importance`: 0.4 for normal notes, 0.7+ for decisions/preferences/handoffs.

If MCP tools are unavailable, say that tool access appears unavailable and continue with normal Codex file tools; do not pretend memory was written.
