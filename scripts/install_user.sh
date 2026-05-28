#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN_DIR="${HOME}/.local/bin"
PYTHON_BIN="${PYTHON_BIN:-python3}"
WITH_DEPS=1
FORCE=0
DRY_RUN=0

usage() {
  cat <<EOF
Usage: bash scripts/install_user.sh [--no-deps] [--force] [--dry-run]

Install Advanced Agent user-level launchers:
  codexx
  advanced-agent-mcp
  advanced-agentd

Actions:
  1. create .venv if missing
  2. install this project into .venv by default
  3. create symlinks under ~/.local/bin

Options:
  --no-deps   skip pip install step
  --force     replace existing ~/.local/bin entries even if not symlinks to this project
  --dry-run   print actions only
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-deps) WITH_DEPS=0 ;;
    --force) FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'would run:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

ensure_venv() {
  if [ -x "$ROOT/.venv/bin/python" ]; then
    return
  fi
  run "$PYTHON_BIN" -m venv "$ROOT/.venv"
}

install_deps() {
  if [ "$WITH_DEPS" -eq 0 ]; then
    return
  fi
  run "$ROOT/.venv/bin/python" -m pip install -U pip
  run "$ROOT/.venv/bin/python" -m pip install -e "$ROOT"
}

link_launcher() {
  local name="$1"
  local src="$ROOT/bin/$name"
  local dst="$BIN_DIR/$name"
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    local target
    target="$(readlink -f "$dst" || true)"
    if [ "$target" != "$src" ] && [ "$FORCE" -ne 1 ]; then
      echo "refuse to replace existing $dst -> ${target:-not-a-symlink}; pass --force to replace" >&2
      exit 1
    fi
    run rm -f "$dst"
  fi
  local wrapper="$BIN_DIR/$name"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "would write launcher: $wrapper -> bash $src"
  else
    cat > "$wrapper" <<EOF
#!/usr/bin/env bash
exec bash "$src" "\$@"
EOF
    chmod +x "$wrapper"
  fi
}

run mkdir -p "$BIN_DIR"
ensure_venv
install_deps
link_launcher codexx
link_launcher advanced-agent-mcp
link_launcher advanced-agentd

cat <<EOF
Installed Advanced Agent launchers under $BIN_DIR

Verify:
  codexx --help

If codexx is not found, add this to your shell rc:
  export PATH="\$HOME/.local/bin:\$PATH"
EOF
