#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN_DIR="${HOME}/.local/bin"
PYTHON_BIN="${PYTHON_BIN:-}"
WITH_DEPS=1
DRY_RUN=0

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  echo "Refusing to run as root/sudo." >&2
  echo "This installer is user-local and should only write under the invoking user's ~/.local/bin and this project." >&2
  exit 1
fi

usage() {
  cat <<EOF
Usage: bash scripts/install_user.sh [--no-deps] [--dry-run]

Install the Advanced Agent user-level launcher:
  codexx

Actions:
  1. create .venv if missing (requires Python 3.11+)
  2. install this project into .venv by default
  3. create ~/.local/bin/codexx

Options:
  --no-deps   skip pip install step
  --dry-run   print actions only
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-deps) WITH_DEPS=0 ;;
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
  if [ -s "$ROOT/.venv/bin/python" ] && "$ROOT/.venv/bin/python" -c 'import sys' >/dev/null 2>&1; then
    if "$ROOT/.venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      return
    fi
    echo "Existing virtualenv uses unsupported Python: $ROOT/.venv" >&2
    echo "Python 3.11+ is required. Move/remove .venv yourself, or set PYTHON_BIN and retry after cleanup." >&2
    exit 1
  elif [ -e "$ROOT/.venv" ]; then
    echo "Existing .venv is not a working Python virtualenv: $ROOT/.venv" >&2
    echo "Refusing to delete or overwrite it automatically. Move/remove .venv yourself and retry." >&2
    exit 1
  fi

  if [ -z "$PYTHON_BIN" ]; then
    local candidate
    for candidate in python3.13 python3.12 python3.11 python3; do
      if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
      fi
    done
  fi

  if [ -z "$PYTHON_BIN" ] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Python 3.11+ is required, but no suitable interpreter was found." >&2
    echo "Install python3.11-venv or set PYTHON_BIN=/path/to/python3.11 and retry." >&2
    exit 1
  fi
  if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "Python 3.11+ is required, but $PYTHON_BIN is too old." >&2
    echo "Set PYTHON_BIN=/path/to/python3.11 and retry." >&2
    exit 1
  fi

  run "$PYTHON_BIN" -m venv --copies "$ROOT/.venv"
  if [ "$DRY_RUN" -eq 0 ] && ! "$ROOT/.venv/bin/python" -c 'import sys' >/dev/null 2>&1; then
    echo "failed to create a working virtualenv: $ROOT/.venv" >&2
    exit 1
  fi
  if [ "$DRY_RUN" -eq 0 ] && ! "$ROOT/.venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "failed to create a Python 3.11+ virtualenv: $ROOT/.venv" >&2
    exit 1
  fi
}

install_deps() {
  if [ "$WITH_DEPS" -eq 0 ]; then
    return
  fi
  run "$ROOT/.venv/bin/python" -m ensurepip --upgrade
  run "$ROOT/.venv/bin/python" -m pip --default-timeout 120 --retries 10 install --upgrade "pip>=23.0" "setuptools>=64" wheel
  run "$ROOT/.venv/bin/python" -m pip --default-timeout 120 --retries 10 install -e "$ROOT"
}

link_launcher() {
  local name="$1"
  local src="$ROOT/bin/$name"
  local dst="$BIN_DIR/$name"
  if [ -e "$dst" ] || [ -L "$dst" ]; then
    local target
    target="$(readlink -f "$dst" || true)"
    local generated_wrapper=0
    if [ -f "$dst" ] && grep -Fxq "exec bash \"$src\" \"\$@\"" "$dst"; then
      generated_wrapper=1
    fi
    if [ "$target" != "$src" ] && [ "$generated_wrapper" -ne 1 ]; then
      echo "refuse to replace existing $dst -> ${target:-not-a-symlink}" >&2
      echo "Move/remove that file yourself if you want this installer to create codexx there." >&2
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

cat <<EOF
Installed Advanced Agent launcher:
  $BIN_DIR/codexx

Verify:
  codexx --help

If codexx is not found, add this to your shell rc:
  export PATH="\$HOME/.local/bin:\$PATH"

Only ~/.local/bin/codexx is installed outside this project. The MCP server and
daemon entry points remain project-local/.venv-local implementation details.
EOF
