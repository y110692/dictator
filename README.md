# Dictator Whisper

Hotkey dictation for Windows and macOS. Press a global hotkey, speak, release it; the app sends the recording to OpenRouter, copies the transcript to the clipboard, and pastes it into the active text field.

There are separate launchers for each OS:

- Windows: `dictator_app.py`, `install.ps1`, `run.ps1`
- macOS: `dictator_app_macos.py`, `install_macos.sh`, `run_macos.sh`

## Features

- Global hotkey dictation.
- Configurable hotkey through `.env` or launch arguments.
- OpenRouter transcription, defaulting to `openai/whisper-1` with `openai/gpt-audio-mini` fallback.
- Tray/menu-bar icon with status dot: green ready, red recording, yellow transcribing.
- Local debug log and last recorded WAV.
- Optional autostart on Windows login or macOS login.

## Requirements

- OpenRouter API key with credits: <https://openrouter.ai/keys>
- Python 3.11 or 3.12.
- Working microphone.

Platform notes:

- Windows 10 or Windows 11.
- macOS requires Microphone and Accessibility permissions for the terminal/Python process that runs the app.

## Windows Install

Open PowerShell in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -ApiKey "YOUR_OPENROUTER_API_KEY" -Autostart
```

Without autostart:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -ApiKey "YOUR_OPENROUTER_API_KEY"
```

Set a hotkey during install:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -ApiKey "YOUR_OPENROUTER_API_KEY" -Hotkey "f9"
```

Run manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Override hotkey for one run:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 -Hotkey "f9"
```

Windows autostart file:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DictatorWhisper.vbs
```

Delete that file to disable Windows autostart.

## macOS Install

Open Terminal in the project folder:

```bash
chmod +x install_macos.sh run_macos.sh
./install_macos.sh --api-key "YOUR_OPENROUTER_API_KEY" --autostart
```

Without autostart:

```bash
chmod +x install_macos.sh run_macos.sh
./install_macos.sh --api-key "YOUR_OPENROUTER_API_KEY"
```

Set a hotkey during install:

```bash
./install_macos.sh --api-key "YOUR_OPENROUTER_API_KEY" --hotkey "f9"
```

Run manually:

```bash
./run_macos.sh
```

Override hotkey for one run:

```bash
./run_macos.sh --hotkey "cmd+shift+d"
```

macOS autostart file:

```text
~/Library/LaunchAgents/com.dictator.whisper.plist
```

Disable macOS autostart:

```bash
launchctl unload ~/Library/LaunchAgents/com.dictator.whisper.plist
rm ~/Library/LaunchAgents/com.dictator.whisper.plist
```

macOS permissions:

1. Open System Settings.
2. Go to Privacy & Security.
3. Allow Microphone for Terminal, iTerm, or the Python app you use.
4. Allow Accessibility for Terminal, iTerm, or the Python app you use.

If global hotkeys or paste do not work on macOS, this is usually an Accessibility permission issue.

## Usage

Default hotkey:

```text
f10
```

Use it like this:

1. Click into any text field.
2. Hold the configured hotkey.
3. Speak.
4. Release the hotkey.
5. Wait for the transcript to paste.

Hotkey behavior:

- Single key, for example `f10` or `f9`: hold-to-talk.
- Combination, for example `ctrl+alt+space` on Windows or `cmd+shift+d` on macOS: toggle mode. Press once to start recording, press again to stop.

## Configuration

The installers create `.env`. You can also copy `.env.example` to `.env` and edit it manually.

```text
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openai/whisper-1
OPENROUTER_FALLBACK_MODEL=openai/gpt-audio-mini
OPENROUTER_API_URL=https://openrouter.ai/api/v1/chat/completions
OPENROUTER_TIMEOUT=120
OPENROUTER_TRANSCRIPTION_PROMPT=Transcribe this Russian speech to plain text. Return only the transcript.
DICTATOR_HOTKEY=f10
DICTATOR_LOG_FILE=runtime/dictator.log
```

Hotkey can be changed in either place:

- Persistent: edit `DICTATOR_HOTKEY` in `.env`.
- One run only: pass `-Hotkey` on Windows or `--hotkey` on macOS.

Examples:

```text
DICTATOR_HOTKEY=f9
DICTATOR_HOTKEY=ctrl+alt+space
DICTATOR_HOTKEY=cmd+shift+d
```

## Logs And Local Files

Runtime files are intentionally ignored by Git:

```text
.env
.venv
runtime
__pycache__
dist
```

Useful debug files:

```text
runtime/dictator.log
runtime/last_recording.wav
```

`last_recording.wav` is overwritten on every recording and is sent to OpenRouter for transcription.

## Troubleshooting

If nothing is pasted, check `runtime/dictator.log`. A successful path includes:

```text
Hotkey press event
AudioRecorder.stop wrote=...
OpenRouter response ... status=200
Recognized: ...
Sent Ctrl+V result: True
```

On macOS the paste line is:

```text
Sent Command+V result: True
```

If recording is empty or too quiet, set the correct default microphone in system settings.

If OpenRouter returns errors for `openai/whisper-1`, keep the fallback enabled. The app will retry with `openai/gpt-audio-mini`.

If the hotkey conflicts with another app, set another one in `.env`.

## Security

Do not commit `.env`. It contains your OpenRouter API key and is already listed in `.gitignore`.
