#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_EXE="$VENV_DIR/bin/python"
API_KEY=""
HOTKEY="f10"
AUTOSTART=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-key)
      API_KEY="${2:-}"
      shift 2
      ;;
    --hotkey)
      HOTKEY="${2:-f10}"
      shift 2
      ;;
    --autostart)
      AUTOSTART=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

find_python() {
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info[:2] in {(3, 11), (3, 12)} else 1)
PY
      then
        command -v "$candidate"
        return 0
      fi
    fi
  done

  if command -v uv >/dev/null 2>&1; then
    uv python install 3.12
    uv python find 3.12
    return 0
  fi

  echo "Python 3.11 or 3.12 is required. Install Python from https://www.python.org/downloads/macos/ or install uv." >&2
  return 1
}

cd "$PROJECT_ROOT"

if [[ ! -x "$PYTHON_EXE" ]]; then
  BASE_PYTHON="$(find_python)"
  "$BASE_PYTHON" -m venv "$VENV_DIR"
fi

"$PYTHON_EXE" -m pip install --upgrade pip setuptools wheel
"$PYTHON_EXE" -m pip install --upgrade -r "$PROJECT_ROOT/requirements.txt"

if [[ -n "$API_KEY" ]]; then
  cat > "$PROJECT_ROOT/.env" <<EOF
TRANSCRIPTION_API_KEY=$API_KEY
TRANSCRIPTION_MODEL=openai/whisper-1
TRANSCRIPTION_FALLBACK_MODEL=
TRANSCRIPTION_API_URL=https://openrouter.ai/api/v1/audio/transcriptions
TRANSCRIPTION_TIMEOUT=120
TRANSCRIPTION_LANGUAGE=ru
TRANSCRIPTION_PROMPT=Transcribe this Russian speech to plain text. Return only the transcript.
TRANSCRIPTION_REFERER=https://localhost/dictator
TRANSCRIPTION_TITLE=Dictator
DICTATOR_HOTKEY=$HOTKEY
DICTATOR_LOG_FILE=runtime/dictator.log
EOF
elif [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
  echo "Created .env from .env.example. Edit TRANSCRIPTION_API_KEY before running."
fi

chmod +x "$PROJECT_ROOT/scripts/macos/run_macos.sh"

if [[ "$AUTOSTART" -eq 1 ]]; then
  LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
  PLIST_PATH="$LAUNCH_AGENTS/com.dictator.whisper.plist"
  mkdir -p "$LAUNCH_AGENTS" "$PROJECT_ROOT/runtime"
  cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dictator.whisper</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd "$PROJECT_ROOT" && ./scripts/macos/run_macos.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$PROJECT_ROOT/runtime/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$PROJECT_ROOT/runtime/launchd.err.log</string>
</dict>
</plist>
EOF
  launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
  launchctl load "$PLIST_PATH"
fi

echo ""
echo "Install complete."
echo "Run: ./scripts/macos/run_macos.sh"
echo "Hotkey: $HOTKEY"
echo "Grant Microphone and Accessibility permissions if macOS asks."
