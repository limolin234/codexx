#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="$BIN_DIR/codexx"
EXPECTED_SRC="$ROOT/bin/codexx"

usage() {
  cat <<EOF
Usage: bash scripts/remove_guidance.sh

Checks only ~/.local/bin/codexx.
Prints a safe manual rm command when it matches this project.
Does not delete files automatically.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi
if [ "$#" -ne 0 ]; then
  echo "unknown argument(s): $*" >&2
  usage >&2
  exit 2
fi

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  echo "Refusing to run as root/sudo." >&2
  echo "Run this as the normal user so HOME resolves to that user's home directory." >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  HASH_TOOL="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  HASH_TOOL="shasum"
else
  echo "No sha256 tool found; refusing to guess whether the launcher is safe to remove." >&2
  exit 1
fi

sha256() {
  if [ "$HASH_TOOL" = "sha256sum" ]; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

sha256_stdin() {
  if [ "$HASH_TOOL" = "sha256sum" ]; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

expected_hash="$(printf '#!/usr/bin/env bash\nexec bash "%s" "$@"\n' "$EXPECTED_SRC" | sha256_stdin)"

if [ ! -e "$LAUNCHER" ] && [ ! -L "$LAUNCHER" ]; then
  echo "No launcher found: $LAUNCHER"
  exit 0
fi

if [ -L "$LAUNCHER" ]; then
  target="$(readlink -f "$LAUNCHER" || true)"
  echo "Found symlink: $LAUNCHER -> ${target:-unresolved}"
  if [ "$target" = "$EXPECTED_SRC" ]; then
    echo "Matches this project. To remove:"
    printf '  rm -i -- %q\n' "$LAUNCHER"
    exit 0
  fi
  echo "Not this project's launcher; leaving untouched."
  exit 1
fi

if [ -f "$LAUNCHER" ]; then
  actual_hash="$(sha256 "$LAUNCHER")"
  echo "Found file: $LAUNCHER"
  if [ "$actual_hash" = "$expected_hash" ]; then
    echo "Matches this project. To remove:"
    printf '  rm -i -- %q\n' "$LAUNCHER"
    exit 0
  fi
  echo "Hash mismatch; leaving untouched."
  echo "expected: $expected_hash"
  echo "actual:   $actual_hash"
  exit 1
fi

echo "Launcher is not a regular file or symlink; leaving untouched."
exit 1
