# System/user-level changes made by Advanced Agent setup

This file records changes outside the source tree that were made to make the
project easier to run.

## User PATH symlinks

Default install creates one launcher in the user's local bin directory:

```text
~/.local/bin/codexx -> <project>/bin/codexx
```

Purpose:

- `codexx`: start enhanced interactive Codex without manually activating venv; it preserves the caller's current directory as Codex's open/work location.

The MCP server and daemon entry points remain project-local/.venv-local
implementation details. They are not added to `~/.local/bin` by default.

This is a user-level launcher only. No global system files, shell rc files,
`~/.codex/config.toml`, or root-owned paths are intentionally modified. If
`~/.local/bin` is not already on `PATH`, the user may choose to add:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

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

The helper is intentionally non-destructive. It refuses to run as root/sudo,
checks whether `~/.local/bin/codexx` appears to be this project's generated
launcher, prints sha256 evidence, and then prints the exact `rm -i` command for
manual removal. It does not remove files automatically.
