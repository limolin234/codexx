# Operations

This project aims for a conservative local footprint.

## Install

```bash
cp .env.example.json .env.json
bash scripts/install.sh
```

The installer creates or reuses the project `.venv`, installs the package editable in that venv, and creates only the user-level launcher:

```text
~/.local/bin/codexx
```

It should not modify system Python, `/usr/bin`, shell rc files, or global Codex config by default.

## Remove guidance

```bash
bash scripts/remove_guidance.sh
```

The remove helper checks whether `~/.local/bin/codexx` is the generated launcher and prints a manual `rm -i` command. It should not automatically delete user files.

## Generated/local state

- `.venv/` - project Python environment
- `runtime/` - runtime SQLite and transient diagnostic state
- `memory/` - durable memory and raw-tail sidecars
- `runtime/codex_interactive/` - diagnostic overflow; check size with `du -sh`

## Detailed docs

- `system_changes.md`
- `../codex/codexx_entrypoint.md`
- `../memory/memory_directory.md`
