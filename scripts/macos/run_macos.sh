#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_EXE="$PROJECT_ROOT/.venv/bin/python"
HOTKEY=""
LAZY=0
NO_TRAY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hotkey)
      HOTKEY="${2:-}"
      shift 2
      ;;
    --lazy)
      LAZY=1
      shift
      ;;
    --no-tray)
      NO_TRAY=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "$PYTHON_EXE" ]]; then
  echo "Virtual environment not found. Run ./scripts/macos/install_macos.sh first." >&2
  exit 1
fi

args=()
if [[ -n "$HOTKEY" ]]; then
  args+=(--hotkey "$HOTKEY")
fi
if [[ "$LAZY" -eq 1 ]]; then
  args+=(--lazy)
fi
if [[ "$NO_TRAY" -eq 1 ]]; then
  args+=(--no-tray)
fi

exec "$PYTHON_EXE" "$PROJECT_ROOT/src/macos/dictator_app_macos.py" "${args[@]}"
