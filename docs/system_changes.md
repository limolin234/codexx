# System/user-level changes made by Advanced Agent setup

This file records changes outside the source tree that were made to make the
project easier to run.

## User PATH symlinks

Created symlinks in the user's local bin directory:

```text
~/.local/bin/codexx -> <project>/bin/codexx
~/.local/bin/advanced-agent-mcp -> <project>/bin/advanced-agent-mcp
~/.local/bin/advanced-agentd -> <project>/bin/advanced-agentd
```

Purpose:

- `codexx`: start enhanced interactive Codex without manually activating venv; it preserves the caller's current directory as Codex's open/work location.
- `advanced-agent-mcp`: run the project-local MCP server.
- `advanced-agentd`: run the long-running deterministic runtime daemon.

These are user-level symlinks only. No global system files, shell rc files, or
root-owned paths were intentionally modified.

## Project-local generated launchers

Created project scripts:

```text
bin/codexx
bin/advanced-agent-mcp
bin/advanced-agentd
```

Created/updated venv-local launchers:

```text
.venv/bin/codexx
.venv/bin/advanced-agent-mcp
.venv/bin/advanced-agentd
```

These are inside the project and can be removed with the project if desired.

## Removal

Use:

```bash
bash scripts/remove_system_changes.sh
```

By default it removes only the user-level symlinks in `~/.local/bin` that point
back to this project. Use `--project-local` if you also want to remove generated
project launcher scripts under `bin/` and `.venv/bin/`, including `codexx`,
`advanced-agent-mcp`, and `advanced-agentd`.
