# `codexx` entrypoint

Preferred first-version startup is now simply:

```bash
codexx
```

The user-level command is a symlink in `~/.local/bin/codexx` pointing to the
project script `bin/codexx`. It auto-activates the project virtualenv internally,
so the shell does not need `source .venv/bin/activate`. `codexx` preserves the
caller's current directory as Codex's default open/work location; only the
Advanced Agent MCP server and runtime files are anchored to this project.

It sets default environment variables before launching the wrapper:

```bash
ADVANCED_AGENT_PROJECT_ROOT=<advanced_agent project>
ADVANCED_AGENT_DB=runtime/advanced_agent.sqlite
ADVANCED_AGENT_CONFIG=.env.json
ADVANCED_AGENT_LOG_DIR=runtime/codex_interactive
ADVANCED_AGENT_SCOPE=project:advanced_agent
ADVANCED_AGENT_MEMORY_TRUST=high
ADVANCED_AGENT_BOOTSTRAP_CHARS=0
```

Relative runtime paths such as `runtime/advanced_agent.sqlite` and `.env.json`
are resolved under `ADVANCED_AGENT_PROJECT_ROOT`, not under the caller's current
directory. So the default single config file is still the project `.env.json`;
normal use does not need extra arguments.

Equivalent explicit command:

```bash
bin/codexx
```

## User-level install

On a new machine, run from the project root:

```bash
bash scripts/install.sh
```

The installer creates `.venv` if needed, installs the project into it, and
writes one user-level launcher under `~/.local/bin`:

```text
codexx
```

The launcher is a small bash wrapper, so the project `bin/codexx` file does not
need executable bits on filesystems that do not preserve Unix mode bits. The
project launcher locates the project root from its own script path rather than a
machine-specific absolute path.

Skip dependency installation when the venv is already prepared:

```bash
bash scripts/install.sh --no-deps
```

The wrapper then injects the local MCP server into Codex with temporary `-c`
overrides. Codex gets a small model-facing tool set: `context_get`,
`memory_write`, `session_raw_tail`, and `project_info`. Low-level memory search
and recent helpers remain internal behind `context_get`.

## Runtime instruction layering

`codexx` does not rely on the Advanced Agent checkout's `AGENTS.md` being read as
the active project instruction file.  The active project is the caller's current
working directory, so its own `AGENTS.md` / `AGENT.md` files remain the coding
instructions for that workspace.

To make the wrapper behavior reliable without mutating `~/.codex/config.toml`,
`codexx` generates a per-session instruction file under
`runtime/codex_interactive/` and passes it to Codex with a temporary
`-c model_instructions_file=...` override.  The generated file contains:

1. the user's configured global Codex instructions, when
   `~/.codex/config.toml` has `model_instructions_file`;
2. the project-local `docs/codexx_runtime_instructions.md` contract, which tells
   Codex how to use Advanced Agent MCP memory/tools and how to keep wrapper
   memory separate from target-project instructions.

This keeps Advanced Agent's memory-source policy project-owned and reproducible,
while preserving the user's normal global Codex preferences for `codexx` runs.

## Startup memory behavior

Default startup is quiet. `codexx` no longer appends a fixed raw-tail prompt when
it is launched with no explicit Codex prompt or subcommand. This avoids an
empty-session assistant reply before the user's first real question, and avoids
spending tokens on raw dialogue that may not be relevant.

The intended first-turn behavior is recall-on-demand:

- project instructions tell Codex to call `context_get` only for
  context-dependent requests, so relevant habits, project preferences, and prior
  decisions are retrieved through tools instead of repeated manual injection;
- raw prior dialogue is retrieved through `session_raw_tail` or `context_get`,
  instead of being pushed at startup;
- explicit long-term vector lookup also goes through `context_get`;
- `memory_write` remains the durable path for decisions, preferences, progress,
  and handoffs.

During interactive `codexx`, a lightweight background runtime queue consumes
due `runtime_hooks` while the Codex PTY is alive and flushes briefly on exit.
This gives memory/profile/compaction maintenance a normal automatic path without
requiring users to manually run `advanced-agentd --once` after every session.
The request-time prompt path still stays tool-driven; the background queue only
processes scheduled maintenance work.

Environment controls:

- `ADVANCED_AGENT_CODEXX_BACKGROUND_MAINTENANCE=0` disables the codexx-owned
  background queue.
- `ADVANCED_AGENT_CODEXX_MAINTENANCE_TICK=2.0` controls the tick interval.
- `ADVANCED_AGENT_CODEXX_EXIT_FLUSH_SECONDS=3.0` controls the best-effort exit
  flush window.

`memory_write` is intentionally a vector-memory/database operation only. It
does not imply writing markdown memory notes. Human/git-facing markdown files
such as project progress logs, handoff documents, or docs should be edited only
when the user asks for that artifact; they are not coupled to routine memory
writes.

For debugging or a manual continuation session, raw-tail startup injection is
still available as an opt-in:

```bash
codexx --bootstrap-chars 1200
# or
ADVANCED_AGENT_BOOTSTRAP_CHARS=1200 codexx
```

If the user supplies an explicit Codex prompt or subcommand, for example
`codexx "do this exact thing"` or `codexx exec ...`, the wrapper does not append
any bootstrap prompt unless that future behavior is explicitly changed.

## Interrupt behavior

`codexx` treats `Ctrl+C` as a wrapper-level stop request. The wrapper writes an
interrupt marker to the session log, terminates the wrapped Codex process group
promptly, ingests a cleaned log tail into memory, and exits with code `130`.

This avoids waiting for Codex-side timeouts while still preserving a resumable
handoff record. The ingested memory removes ANSI terminal escape sequences and
marks interrupted sessions as `interrupted and saved`.

## Memory trust policy

Codex instructions now tell the model to trust Advanced Agent vector memory as the
durable project memory layer:

- call `context_get` for previous-context/project-state questions; if setting
  `mode`, use only `supplement` or `full`;
- call `context_get` for explicit long-term memory lookup;
- call `memory_write` for records, decisions, preferences, and handoffs;
- if vector memory returns relevant records, use them instead of claiming that no
  previous context is visible.
