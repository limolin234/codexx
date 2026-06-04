#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BIN_DIR="${HOME}/.local/bin"
LAUNCHER="$BIN_DIR/codexx"
EXPECTED_SRC="$ROOT/bin/codexx"

usage() {
  cat <<EOF
Usage: bash scripts/remove_system_changes.sh

Conservative uninstall helper for the user-level launcher:
  ~/.local/bin/codexx

This script does not delete files automatically. It verifies whether the
launcher appears to be this project's generated wrapper, prints sha256 evidence,
and then prints the exact manual rm command if removal is safe.
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

echo "Project root: $ROOT"
echo "Expected launcher: $LAUNCHER"
echo "Expected target: $EXPECTED_SRC"
echo "Expected generated-wrapper sha256: $expected_hash"
echo

if [ ! -e "$LAUNCHER" ] && [ ! -L "$LAUNCHER" ]; then
  echo "No user-level codexx launcher found at: $LAUNCHER"
  exit 0
fi

if [ -L "$LAUNCHER" ]; then
  target="$(readlink -f "$LAUNCHER" || true)"
  echo "Found symlink: $LAUNCHER -> ${target:-unresolved}"
  if [ "$target" = "$EXPECTED_SRC" ]; then
    echo "Safe manual removal command:"
    printf '  rm -i -- %q\n' "$LAUNCHER"
    exit 0
  fi
  echo "Not this project's expected launcher; leaving it untouched."
  exit 1
fi

if [ -f "$LAUNCHER" ]; then
  actual_hash="$(sha256 "$LAUNCHER")"
  echo "Found file: $LAUNCHER"
  echo "Actual sha256: $actual_hash"
  if [ "$actual_hash" = "$expected_hash" ]; then
    echo "Safe manual removal command:"
    printf '  rm -i -- %q\n' "$LAUNCHER"
    exit 0
  fi
  echo "Hash does not match this project's generated wrapper; leaving it untouched."
  exit 1
fi

echo "Launcher exists but is neither a regular file nor symlink; leaving it untouched."
exit 1
