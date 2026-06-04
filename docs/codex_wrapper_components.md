# Codex wrapper component map

This file records where the current `codexx` / interactive Codex wrapper pieces
live, and what can be upgraded next.

## Current entry path

```text
user shell
  -> ~/.local/bin/codexx                         user-level symlink
  -> bin/codexx                                  project launcher
  -> .venv/bin/python -m advanced_agent.codex_interactive
  -> src/advanced_agent/codex_interactive.py     PTY wrapper + MCP injection
  -> codex                                      original Codex CLI
```

The wrapper is intentionally thin around Codex: it keeps Codex's native terminal
UI, while adding project-local runtime config, MCP tools, terminal logging, and
memory ingestion.

## Files and responsibilities

### User-visible launcher

- `~/.local/bin/codexx`
  - User-level symlink, not tracked in the repo.
  - Points to this checkout's `bin/codexx`.
  - Recorded in `docs/system_changes.md`.
- `bin/codexx`
  - Bash launcher.
  - Finds the project-local `.venv`.
  - Sets `PATH`, `PYTHONPATH`, and default `ADVANCED_AGENT_*` environment
    variables.
  - Executes `python -m advanced_agent.codex_interactive`.
- `pyproject.toml`
  - Defines venv-local package console scripts:
    - `codexx`
    - `advanced-agent-mcp`
    - `advanced-agentd`
  - User-level install exposes only `codexx`; MCP and daemon scripts are
    project-local/.venv-local implementation/debug entry points.

### Python wrapper core

- `src/advanced_agent/codex_interactive.py`
  - Main wrapper implementation.
  - Builds Codex environment variables.
  - Injects MCP server into Codex via temporary `codex -c mcp_servers...`
    overrides.
  - Starts Codex under a child PTY.
  - Switches the parent terminal into raw mode so arrow keys and control keys
    work.
  - Mirrors terminal bytes to `runtime/codex_interactive/*.terminal.log`.
  - Handles wrapper-level `Ctrl+C`, terminates the Codex process group, and
    exits `130`.
  - Cleans the transcript tail and appends it to the bounded session raw-tail
    buffer for short-term inspection only. It does not create durable raw-log
    memory records on close.

### Defaults and config

- `src/advanced_agent/defaults.py`
  - Central default values:
    - runtime DB
    - config path
    - log dir
    - default session title
    - memory scope
    - MCP server name
  - Reads environment overrides such as `ADVANCED_AGENT_DB`.
- `.env.json`
  - Project-local runtime config.
- `.env.example.json`
  - Template config.

### MCP/runtime tool side

- `src/advanced_agent/mcp_server.py`
  - MCP protocol adapter.
  - Exposes runtime tools to Codex.
  - Should stay a thin adapter.
- `src/advanced_agent/runtime_tools.py`
  - Real MCP tool implementation layer.
  - Includes memory/context/session/task/project/workdir tools.
  - Business logic should live here or below, not in the MCP protocol wrapper.
- `src/advanced_agent/runtime/app.py`
  - Builds the runtime application used by the wrapper and MCP server.
- `src/advanced_agent/memory_indexer.py`
  - Indexes explicit durable memories such as handoffs, decisions, and
    verifications. Wrapper raw transcript tails are intentionally not routed
    through it.
- `src/advanced_agent/memory_facets.py`
  - Keeps facet policy for durable memory types and legacy raw-log cleanup.

### Runtime outputs

- `runtime/advanced_agent.sqlite`
  - Main runtime SQLite DB.
- `runtime/codex_interactive/*.terminal.log`
  - Raw-ish PTY byte stream logs for each wrapped Codex session.
  - These are useful for recovery, but should not be treated as clean semantic
    history.

### Documentation

- `docs/codexx_entrypoint.md`
  - User-facing startup behavior and memory-trust policy.
- `docs/enhanced_interactive_codex.md`
  - Wrapper architecture note.
- `docs/codex_mcp_memory_quickstart.md`
  - MCP quickstart and debugging notes.
- `docs/system_changes.md`
  - User/system-level changes and how to remove them.
- `scripts/remove_system_changes.sh`
  - Removes user-level symlinks created for the project.

### Tests

- `tests/core/test_codex_interactive_wrapper.py`
  - Wrapper env/config/log-cleaning tests.
- `tests/core/test_defaults_entrypoint.py`
  - Entrypoint/default behavior tests.
- `tests/core/test_mcp_server.py`
  - MCP tool exposure tests.
- `tests/core/test_runtime_tools.py`
  - Runtime tool behavior tests.

## Upgrade candidates

### 1. Move wrapper defaults into one config object

Current state:

- Some defaults live in `defaults.py`.
- Some runtime env construction lives in `bin/codexx`.
- Some MCP env construction lives in `codex_interactive.py`.

Upgrade:

- Add a small `CodexWrapperConfig` dataclass.
- Let both `bin/codexx` and Python wrapper converge on the same documented
  names.
- Reduce duplicated defaults and make tests assert one source of truth.

### 2. Replace raw PTY-log memory with structured session events

Current state:

- The wrapper records PTY bytes and ingests a cleaned tail.
- This preserves recovery evidence, but semantic quality is limited.

Upgrade:

- Keep PTY logs as evidence.
- Add wrapper-side structured events:
  - wrapper started
  - Codex args
  - MCP enabled/disabled
  - interrupted
  - exit code
  - log path
- Prefer explicit `memory.write` or end-of-session summaries for semantic
  memories.

### 3. Add a wrapper doctor command

Current state:

- Failures such as missing `codex`, missing venv, bad MCP injection, or bad
  symlink must be diagnosed manually.

Upgrade:

- Add `codexx --doctor` or `advanced-agent doctor codexx`.
- Check:
  - `~/.local/bin/codexx` points to this project.
  - `.venv/bin/python` exists.
  - `codex` is on `PATH`.
  - `.env.json` exists.
  - MCP server starts.
  - DB path is writable.
  - terminal is a TTY.

### 4. Make project scope less hard-coded

Current state:

- `ADVANCED_AGENT_SCOPE` defaults to `project:advanced_agent`.
- Good for this project, but not ideal for using `codexx` across many external
  working directories.

Upgrade:

- Keep Advanced Agent's own runtime anchored here.
- Derive a separate `work_scope` from the caller's cwd/project root.
- Use that scope for project memories while keeping wrapper implementation
  memories under `project:advanced_agent`.

### 5. Better interrupt/resume semantics

Current state:

- `Ctrl+C` terminates Codex and saves an interrupted log tail.

Upgrade:

- Record an explicit resumable handoff note when interrupted.
- Optionally print a short suggested resume command.
- Later: if Codex exposes stable structured session IDs, link wrapper session
  and Codex internal session more precisely.

### 6. Keep MCP injection as a pure adapter

Current state:

- This is mostly true already: `mcp_server.py` adapts `RuntimeToolBridge`.

Upgrade:

- Add tests that assert each MCP tool maps to runtime bridge behavior.
- Avoid putting memory/tool business logic into `codex_interactive.py` or
  `mcp_server.py`.

## Recommended next step

The most useful next upgrade is **wrapper doctor + component centralization**:

1. Add `CodexWrapperConfig` in Python.
2. Add `--doctor`.
3. Test missing `codex`, bad venv, bad config, bad DB path, and MCP config arg
   generation.

This improves daily usability without changing the core architecture.
