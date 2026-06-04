#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
REMOVE_PROJECT_LOCAL=0
DRY_RUN=0

usage() {
  cat <<EOF
Usage: bash scripts/remove_system_changes.sh [--project-local] [--dry-run]

Removes user-level launchers created by this project:
  ~/.local/bin/codexx

It also removes legacy advanced-agent-mcp / advanced-agentd launchers when they
point back to this project.

Options:
  --project-local  also remove generated project launchers under bin/ and .venv/bin/
  --dry-run        print actions without removing
EOF
}

for arg in "$@"; do
  case "$arg" in
    --project-local) REMOVE_PROJECT_LOCAL=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

remove_if_project_launcher() {
  local path="$1"
  local src="$2"
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    echo "skip missing: $path"
    return
  fi
  if [ -f "$path" ] && grep -Fxq "exec bash \"$src\" \"\$@\"" "$path"; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "would remove: $path -> bash $src"
    else
      rm -f "$path"
      echo "removed: $path -> bash $src"
    fi
    return
  fi
  if [ ! -L "$path" ]; then
    echo "skip not project launcher: $path"
    return
  fi
  local target
  target="$(readlink -f "$path" || true)"
  case "$target" in
    "$ROOT"/*)
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "would remove: $path -> $target"
      else
        rm -f "$path"
        echo "removed: $path -> $target"
      fi
      ;;
    *)
      echo "skip symlink outside project: $path -> $target"
      ;;
  esac
}

remove_project_file() {
  local path="$1"
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    echo "skip missing: $path"
    return
  fi
  case "$(readlink -f "$path" || true)" in
    "$ROOT"/*)
      if [ "$DRY_RUN" -eq 1 ]; then
        echo "would remove project file: $path"
      else
        rm -f "$path"
        echo "removed project file: $path"
      fi
      ;;
    *) echo "skip outside project: $path" ;;
  esac
}

remove_if_project_launcher "$HOME/.local/bin/codexx" "$ROOT/bin/codexx"
remove_if_project_launcher "$HOME/.local/bin/advanced-agent-mcp" "$ROOT/bin/advanced-agent-mcp"
remove_if_project_launcher "$HOME/.local/bin/advanced-agentd" "$ROOT/bin/advanced-agentd"

if [ "$REMOVE_PROJECT_LOCAL" -eq 1 ]; then
  remove_project_file "$ROOT/bin/codexx"
  remove_project_file "$ROOT/bin/advanced-agent-mcp"
  remove_project_file "$ROOT/bin/advanced-agentd"
  remove_project_file "$ROOT/.venv/bin/codexx"
  remove_project_file "$ROOT/.venv/bin/advanced-agent-mcp"
  remove_project_file "$ROOT/.venv/bin/advanced-agentd"
fi
