# Dictator

Hotkey dictation for Windows and macOS. Press a global hotkey, speak, release it; the app sends the recording to the configured transcription provider, copies the transcript to the clipboard, and pastes it into the active text field.

There are separate launchers for each OS:

- Windows: `src/windows/dictator_app.py`, `scripts/windows/install.ps1`, `scripts/windows/run.ps1`
- macOS: `src/macos/dictator_app_macos.py`, `scripts/macos/install_macos.sh`, `scripts/macos/run_macos.sh`

## Project Layout

```text
assets/icons/          app icons
scripts/windows/       Windows install and run scripts
scripts/macos/         macOS install and run scripts
src/windows/           Windows app source
src/macos/             macOS app source
runtime/               local logs and last recording, ignored by Git
```

## Features

- Global hotkey dictation.
- Configurable hotkey through `.env` or launch arguments.
- Configurable transcription provider. The default is OpenRouter `openai/whisper-1` with `openai/gpt-audio-mini` fallback.
- Tray/menu-bar icon with status dot: green ready, red recording, yellow transcribing.
- Local debug log and last recorded WAV.
- Optional autostart on Windows login or macOS login.

## Requirements

- API key for OpenRouter or another compatible transcription provider. Default OpenRouter keys: <https://openrouter.ai/keys>
- Python 3.11 or 3.12.
- Working microphone.

Platform notes:

- Windows 10 or Windows 11.
- macOS requires Microphone and Accessibility permissions for the terminal/Python process that runs the app.

## Windows Install

Open PowerShell in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1 -ApiKey "YOUR_API_KEY" -Autostart
```

Without autostart:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1 -ApiKey "YOUR_API_KEY"
```

Set a hotkey during install:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1 -ApiKey "YOUR_API_KEY" -Hotkey "f9"
```

Run manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\run.ps1
```

Override hotkey for one run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\run.ps1 -Hotkey "f9"
```

Windows autostart file:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DictatorWhisper.vbs
```

Delete that file to disable Windows autostart.

## macOS Install

Open Terminal in the project folder:

```bash
chmod +x scripts/macos/install_macos.sh scripts/macos/run_macos.sh
./scripts/macos/install_macos.sh --api-key "YOUR_API_KEY" --autostart
```

Without autostart:

```bash
chmod +x scripts/macos/install_macos.sh scripts/macos/run_macos.sh
./scripts/macos/install_macos.sh --api-key "YOUR_API_KEY"
```

Set a hotkey during install:

```bash
./scripts/macos/install_macos.sh --api-key "YOUR_API_KEY" --hotkey "f9"
```

Run manually:

```bash
./scripts/macos/run_macos.sh
```

Override hotkey for one run:

```bash
./scripts/macos/run_macos.sh --hotkey "cmd+shift+d"
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
TRANSCRIPTION_API_KEY=your_key_here
TRANSCRIPTION_MODEL=openai/whisper-1
TRANSCRIPTION_FALLBACK_MODEL=openai/gpt-audio-mini
TRANSCRIPTION_API_URL=https://openrouter.ai/api/v1/chat/completions
TRANSCRIPTION_TIMEOUT=120
TRANSCRIPTION_PROMPT=Transcribe this Russian speech to plain text. Return only the transcript.
TRANSCRIPTION_REFERER=https://localhost/dictator
TRANSCRIPTION_TITLE=Dictator
DICTATOR_HOTKEY=f10
DICTATOR_LOG_FILE=runtime/dictator.log
```

Provider settings live in `.env`, so you can switch API keys or compatible providers without editing code:

- `TRANSCRIPTION_API_KEY`: provider API key.
- `TRANSCRIPTION_API_URL`: chat completions endpoint.
- `TRANSCRIPTION_MODEL`: primary model.
- `TRANSCRIPTION_FALLBACK_MODEL`: optional retry model; leave empty to disable fallback.
- `TRANSCRIPTION_PROMPT`: transcription instruction sent with the audio.
- `TRANSCRIPTION_REFERER` and `TRANSCRIPTION_TITLE`: optional metadata headers; useful for OpenRouter, usually ignored by other providers.

The built-in request format is OpenAI-compatible `chat/completions` JSON with audio passed as `input_audio` in the message content. That works for OpenRouter and may work with other providers that implement the same format. If a provider uses a different endpoint shape, for example multipart `/audio/transcriptions`, add a small adapter in `OpenRouterWhisperTranscriber._post_transcription`.

Existing `.env` files with `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_FALLBACK_MODEL`, `OPENROUTER_API_URL`, `OPENROUTER_TIMEOUT`, and `OPENROUTER_TRANSCRIPTION_PROMPT` still work. New `TRANSCRIPTION_*` variables take priority when both are present.

Hotkey can be changed in either place:

- Persistent: edit `DICTATOR_HOTKEY` in `.env`.
- One run only: pass `-Hotkey` on Windows or `--hotkey` on macOS.
- Tray/menu bar: right-click/click the app icon, choose `Hotkey...`, press a new hotkey, then click Save.

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

`last_recording.wav` is overwritten on every recording and is sent to the configured transcription provider.

## Troubleshooting

If nothing is pasted, check `runtime/dictator.log`. A successful path includes:

```text
Hotkey press event
AudioRecorder.stop wrote=...
Transcription API response ... status=200
Recognized: ...
Sent Ctrl+V result: True
```

On macOS the paste line is:

```text
Sent Command+V result: True
```

If recording is empty or too quiet, set the correct default microphone in system settings.

If the primary transcription model returns errors, keep the fallback enabled. The app will retry with `TRANSCRIPTION_FALLBACK_MODEL`.

If the hotkey conflicts with another app, set another one in `.env`.

## Security

Do not commit `.env`. It contains your provider API key and is already listed in `.gitignore`.
