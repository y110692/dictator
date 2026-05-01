# Changelog

## 2026-05-01

### Fixed

- Route OpenRouter dictation through `/audio/transcriptions` so the service returns transcript text instead of a chat answer to the spoken message.
- Keep `openai/whisper-1` as the default OpenRouter STT model and disable the old `openai/gpt-audio-mini` chat/audio fallback for STT requests.
- Automatically move legacy OpenRouter `/chat/completions` configuration to the STT endpoint at runtime.
- Add a Russian transcription language hint by default.

### Changed

- Use toggle dictation for single-key and combination hotkeys: press once to start recording, press again to stop, transcribe, and paste.
- Improve Windows hotkey handling with autorepeat guards, target-window restore diagnostics, short-recording protection, and status reset after too-short recordings.
- Make hotkey passthrough the Windows default; `--suppress-hotkey` can still be used when suppression is needed.

### Documentation

- Update `.env.example`, Windows/macOS installers, and README configuration docs for the STT endpoint and new default transcription settings.
