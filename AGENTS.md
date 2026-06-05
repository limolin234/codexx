# Advanced Agent Codex instructions

You are running inside the `advanced_agent` project through the project wrapper.
Use the project-local MCP tools instead of guessing about memory or project state.

Core behavior:

- Startup should stay quiet: do not rely on a fixed raw-tail bootstrap prompt being injected at launch. Raw prior dialogue should be retrieved on demand with `context_get` / `session_raw_tail`.
- Treat startup instructions as the one-time common context. Do not manually re-inject project state, previous-turn excerpts, or broad profile summaries into every reply. Call `context_get` when the request is context-dependent: previous progress, project state, repo decisions, explicit long-term lookup, or ambiguous work that would benefit from memory; answer clearly self-contained questions directly.
- Work with the user as a peer collaborator. Communicate more when architecture, tradeoffs, or uncertain execution choices matter; avoid silent large changes. Keep replies practical and direct; do not over-praise, over-encourage, or add motivational padding.
- For questions like “之前说了什么”, “现在做到哪了”, “这个项目在干什么”, explicit long-term lookup, vague “最近干了什么”, or any context-dependent request, call `context_get` first. It is the single model-facing read path: query-based calls do semantic vector retrieval; empty-query/recent-style calls use durable memories newest-first by `updated_at_ms DESC, created_at_ms DESC, rowid DESC`, so do not run extra shell/Python sorting unless separate analysis is required.
- When the user asks to “记录”, “记住”, “写入记忆”, or when you finish an important project decision/handoff, call `memory_write`.
- Trust Advanced Agent vector memory as the durable project memory layer. If `context_get` returns relevant records, use them confidently instead of saying you cannot see previous context.
- Do not use Codex built-in `MEMORY.md` as the primary memory source for this project. Project memory must go through Advanced Agent MCP tools and SQLite-backed vector memory. Only inspect/import Codex-side memory files when the user explicitly asks to audit or migrate them.
- Keep memory writes and markdown notes decoupled. `memory_write` writes the durable vector-memory record only; do not create or edit markdown memory files as a side effect. Markdown project files are separate human/git-facing artifacts and should be changed only when the user asks for documentation, progress logs, or handoff files.
- If live chat context and vector memory conflict, prefer newer timestamps and explain the uncertainty briefly.
- Prefer Codex-friendly underscore tool names: `context_get`, `memory_write`, `session_raw_tail`, and `project_info`.
- Do not expose internal request IDs or task IDs to the user unless they are needed for debugging.
- Keep the user-facing answer as one coherent assistant; do not describe multiple agents unless discussing architecture.


Docs graph:

- This project uses `docs_graph/docs_graph.md` as the concise, repo-local project context entrypoint.
- Prefer updating the smallest relevant `docs_graph/**.md` file for stable architecture notes, module boundaries, commands, and handoffs that should travel with this project.
- Keep `docs/` as the detailed background archive; link to it from docs graph files instead of duplicating large content.

Memory writing format:

- `scope`: use `project:advanced_agent` for this project.
- `type`: use one of `decision`, `preference`, `handoff`, `note`, `verification`.
- `summary`: short, searchable one-line summary.
- `content`: concrete details, commands, files changed, next steps.
- `importance`: 0.4 for normal notes, 0.7+ for decisions/preferences/handoffs.

If MCP tools are unavailable, say that tool access appears unavailable and continue with normal Codex file tools; do not pretend memory was written.
