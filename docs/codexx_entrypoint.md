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
ADVANCED_AGENT_BOOTSTRAP_CHARS=1200
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
bash scripts/install_user.sh
```

The installer creates `.venv` if needed, installs the project into it, and
writes user-level launchers under `~/.local/bin`:

```text
codexx
advanced-agent-mcp
advanced-agentd
```

The launchers are small bash wrappers, so the project `bin/*` files do not need
executable bits on filesystems that do not preserve Unix mode bits. The project
launchers locate the project root from their own script path rather than a
machine-specific absolute path.

Skip dependency installation when the venv is already prepared:

```bash
bash scripts/install_user.sh --no-deps
```

The wrapper then injects the local MCP server into Codex with temporary `-c`
overrides. Codex gets `context_get`, `memory_write`, `memory_search`, and related
runtime tools automatically.

## Startup bootstrap context

When `codexx` is launched with no explicit Codex prompt or subcommand, the
wrapper appends a small initial prompt to Codex containing about
`ADVANCED_AGENT_BOOTSTRAP_CHARS` characters of recent Advanced Agent raw-tail
history. The default is `1200`, roughly the intended "about one thousand
characters" startup context.

This is only a bounded excerpt. It is meant to let Codex continue the most recent
work without asking the user to restate it. The bootstrap prompt also tells Codex
to use MCP tools for deeper context:

- `context_get`: prior session lines plus vector memory hits.
- `session_raw_tail`: more bounded raw dialogue from the ring-buffer-like tail.
- `memory_search`: explicit long-term vector memory lookup.
- `memory_write`: durable decisions, preferences, progress, and handoffs.

Disable startup context if needed:

```bash
codexx --bootstrap-chars 0
```

If the user supplies an explicit Codex prompt or subcommand, for example
`codexx "do this exact thing"` or `codexx exec ...`, the wrapper does not append
the bootstrap prompt.

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

- call `context_get` for previous-context/project-state questions;
- call `memory_search` for explicit long-term memory lookup;
- call `memory_write` for records, decisions, preferences, and handoffs;
- if vector memory returns relevant records, use them instead of claiming that no
  previous context is visible.
