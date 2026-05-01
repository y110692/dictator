from __future__ import annotations

import argparse
import base64
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
SAMPLE_RATE = 16000
OPENROUTER_CHAT_COMPLETIONS_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
OPENROUTER_MODEL = "openai/whisper-1"
OPENROUTER_LEGACY_CHAT_MODEL = "openai/gpt-audio-mini"
OPENROUTER_FALLBACK_MODEL = ""
DEFAULT_TRANSCRIPTION_PROMPT = "Transcribe this Russian speech to plain text. Return only the transcript."
DEFAULT_TRANSCRIPTION_LANGUAGE = "ru"
DEFAULT_TRANSCRIPTION_REFERER = "https://localhost/dictator"
DEFAULT_TRANSCRIPTION_TITLE = "Dictator"


class TimestampedTee:
    def __init__(self, stream: Any, log_file: Any, stream_name: str) -> None:
        self.stream = stream
        self.log_file = log_file
        self.stream_name = stream_name
        self.lock = threading.Lock()
        self.buffer = ""

    def write(self, text: str) -> int:
        with self.lock:
            if self.stream is not None:
                self.stream.write(text)
                self.stream.flush()

            self.buffer += text
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                self.log_file.write(f"{timestamp} [{self.stream_name}] {line}\n")
                self.log_file.flush()
        return len(text)

    def flush(self) -> None:
        with self.lock:
            if self.stream is not None:
                self.stream.flush()
            if self.buffer:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                self.log_file.write(f"{timestamp} [{self.stream_name}] {self.buffer}\n")
                self.buffer = ""
            self.log_file.flush()


def load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip().lstrip("\ufeff")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name:
            os.environ.setdefault(name, value)


def env_value(name: str, legacy_name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    value = os.environ.get(legacy_name, "").strip()
    if value:
        return value
    return default


def optional_env_value(name: str, legacy_name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ.get(name, "").strip()
    if legacy_name in os.environ:
        return os.environ.get(legacy_name, "").strip()
    return default


def set_env_value(name: str, value: str) -> None:
    env_path = PROJECT_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    output: list[str] = []
    updated = False

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            output.append(raw_line)
            continue

        current_name, _ = raw_line.split("=", 1)
        if current_name.strip().lstrip("\ufeff") == name:
            output.append(f"{name}={value}")
            updated = True
        else:
            output.append(raw_line)

    if not updated:
        output.append(f"{name}={value}")

    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.environ[name] = value


def setup_log_file() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log_path = Path(os.environ.get("DICTATOR_LOG_FILE", RUNTIME_DIR / "dictator.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = TimestampedTee(sys.stdout, log_file, "stdout")  # type: ignore[assignment]
    sys.stderr = TimestampedTee(sys.stderr, log_file, "stderr")  # type: ignore[assignment]
    print("")
    print(f"--- Dictator macOS started, pid={os.getpid()}, log={log_path} ---")


load_env_file()
setup_log_file()

import numpy as np
import pyperclip
import requests
import sounddevice as sd
import soundfile as sf
from pynput import keyboard


def run_osascript(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        check=False,
        text=True,
    )


def describe_frontmost_app() -> str:
    result = run_osascript('tell application "System Events" to get name of first application process whose frontmost is true')
    if result.returncode == 0:
        return result.stdout.strip()
    return f"frontmost_app_error={result.stderr.strip()}"


def send_command_v() -> bool:
    result = run_osascript('tell application "System Events" to keystroke "v" using command down')
    if result.returncode == 0:
        return True
    print(f"Command+V failed: {result.stderr.strip()}", file=sys.stderr)
    return False


def normalize_hotkey_part(part: str) -> str:
    aliases = {
        "command": "cmd",
        "cmd_l": "cmd",
        "cmd_r": "cmd",
        "control": "ctrl",
        "ctrl_l": "ctrl",
        "ctrl_r": "ctrl",
        "option": "alt",
        "alt_l": "alt",
        "alt_r": "alt",
        "shift_l": "shift",
        "shift_r": "shift",
        "escape": "esc",
        "return": "enter",
    }
    value = part.strip().lower()
    return aliases.get(value, value)


def key_names(key: keyboard.Key | keyboard.KeyCode) -> set[str]:
    names: set[str] = set()
    if isinstance(key, keyboard.KeyCode) and key.char:
        names.add(key.char.lower())
        return names

    raw = str(key)
    if raw.startswith("Key."):
        raw = raw[4:]
    normalized = normalize_hotkey_part(raw)
    names.add(normalized)

    if normalized in {"cmd", "ctrl", "alt", "shift"}:
        names.add(normalized)
    if normalized == "space":
        names.add(" ")
    return names


class AudioRecorder:
    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.frames: list[np.ndarray] = []
        self.stream: sd.InputStream | None = None
        self.lock = threading.Lock()

    def start(self) -> None:
        with self.lock:
            if self.stream is not None:
                return
            self.frames = []
            print(f"AudioRecorder.start sample_rate={self.sample_rate}")
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self.stream.start()

    def stop_to_wav(self) -> Path | None:
        with self.lock:
            stream = self.stream
            self.stream = None

        if stream is not None:
            stream.stop()
            stream.close()

        if not self.frames:
            print("AudioRecorder.stop no frames captured")
            return None

        audio = np.concatenate(self.frames, axis=0)
        if audio.ndim > 1:
            audio = audio[:, 0]

        if len(audio) < int(self.sample_rate * 0.25):
            print(f"AudioRecorder.stop too short samples={len(audio)}")
            return None

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        wav_path = RUNTIME_DIR / "last_recording.wav"
        sf.write(str(wav_path), audio, self.sample_rate, subtype="PCM_16")
        duration = len(audio) / self.sample_rate
        rms = float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0
        print(f"AudioRecorder.stop wrote={wav_path} duration={duration:.2f}s rms={rms:.5f} bytes={wav_path.stat().st_size}")
        return wav_path

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        if status:
            print(f"Audio status: {status}", file=sys.stderr)
        self.frames.append(indata.copy())


class OpenRouterWhisperTranscriber:
    def __init__(self) -> None:
        self.api_key: str | None = None
        self.api_url = env_value("TRANSCRIPTION_API_URL", "OPENROUTER_API_URL", OPENROUTER_API_URL)
        self.model = env_value("TRANSCRIPTION_MODEL", "OPENROUTER_MODEL", OPENROUTER_MODEL)
        self.fallback_model = optional_env_value(
            "TRANSCRIPTION_FALLBACK_MODEL",
            "OPENROUTER_FALLBACK_MODEL",
            OPENROUTER_FALLBACK_MODEL,
        )
        self.prompt = env_value("TRANSCRIPTION_PROMPT", "OPENROUTER_TRANSCRIPTION_PROMPT", DEFAULT_TRANSCRIPTION_PROMPT)
        self.language = optional_env_value(
            "TRANSCRIPTION_LANGUAGE",
            "OPENROUTER_TRANSCRIPTION_LANGUAGE",
            DEFAULT_TRANSCRIPTION_LANGUAGE,
        )
        self.timeout = float(env_value("TRANSCRIPTION_TIMEOUT", "OPENROUTER_TIMEOUT", "120"))
        self.referer = optional_env_value("TRANSCRIPTION_REFERER", "OPENROUTER_HTTP_REFERER", DEFAULT_TRANSCRIPTION_REFERER)
        self.title = optional_env_value("TRANSCRIPTION_TITLE", "OPENROUTER_TITLE", DEFAULT_TRANSCRIPTION_TITLE)
        self.lock = threading.Lock()
        self._normalize_openrouter_stt_settings()

    def _uses_stt_endpoint(self) -> bool:
        return self.api_url.rstrip("/").endswith("/audio/transcriptions")

    def _uses_openrouter_stt_endpoint(self) -> bool:
        return "openrouter.ai" in self.api_url.lower() and self._uses_stt_endpoint()

    def _normalize_openrouter_stt_settings(self) -> None:
        if self.api_url.rstrip("/") == OPENROUTER_CHAT_COMPLETIONS_API_URL:
            print("Legacy OpenRouter chat transcription config detected; using /audio/transcriptions.")
            self.api_url = OPENROUTER_API_URL

        if not self._uses_openrouter_stt_endpoint():
            return

        if self.model == OPENROUTER_LEGACY_CHAT_MODEL:
            print(f"Legacy OpenRouter chat audio model {self.model!r} detected; using {OPENROUTER_MODEL!r}.")
            self.model = OPENROUTER_MODEL
        if self.fallback_model == OPENROUTER_LEGACY_CHAT_MODEL:
            print(f"Ignoring legacy chat fallback model {self.fallback_model!r} for STT endpoint.")
            self.fallback_model = ""

    def load(self) -> None:
        with self.lock:
            if self.api_key is not None:
                return

            api_key = env_value("TRANSCRIPTION_API_KEY", "OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError("TRANSCRIPTION_API_KEY is not set. Put it in .env or the process environment.")

            self.api_key = api_key
            print(f"Transcription API ready: {self.model} url={self.api_url}")
            if self._uses_stt_endpoint() and self.language:
                print(f"Transcription language hint: {self.language}")
            if self.fallback_model and self.fallback_model != self.model:
                print(f"Transcription fallback model: {self.fallback_model}")

    def transcribe(self, wav_path: Path) -> str:
        self.load()
        assert self.api_key is not None

        audio_data = base64.b64encode(wav_path.read_bytes()).decode("ascii")
        print(f"Prepared audio upload path={wav_path} base64_chars={len(audio_data)}")

        try:
            data = self._post_transcription(self.model, audio_data)
        except RuntimeError as exc:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            print(f"Primary transcription model failed ({self.model}); retrying {self.fallback_model}: {exc}", file=sys.stderr)
            data = self._post_transcription(self.fallback_model, audio_data)

        return self._extract_transcript(data)

    def _post_transcription(self, model: str, audio_data: str) -> dict[str, Any]:
        started_at = time.monotonic()
        if self._uses_stt_endpoint():
            payload: dict[str, Any] = {
                "model": model,
                "input_audio": {
                    "data": audio_data,
                    "format": "wav",
                },
            }
            if self.language:
                payload["language"] = self.language
        else:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self.prompt},
                            {"type": "input_audio", "input_audio": {"data": audio_data, "format": "wav"}},
                        ],
                    }
                ],
                "stream": False,
            }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-OpenRouter-Title"] = self.title

        with self.lock:
            print(f"Transcription API request model={model} url={self.api_url}")
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=self.timeout)

        elapsed = time.monotonic() - started_at
        print(f"Transcription API response model={model} status={response.status_code} elapsed={elapsed:.2f}s")
        if response.status_code >= 400:
            raise RuntimeError(f"Transcription API error {response.status_code}: {self._extract_error(response)}")

        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"Transcription API returned non-JSON response: {response.text[:500]}") from exc

    def _extract_transcript(self, data: dict[str, Any]) -> str:
        direct_text = data.get("text")
        if isinstance(direct_text, str):
            return direct_text.strip()

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""

        message = choices[0].get("message", {})
        audio = message.get("audio")
        if isinstance(audio, dict) and isinstance(audio.get("transcript"), str):
            return audio["transcript"].strip()

        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts).strip()

        return ""

    def _extract_error(self, response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return response.text[:500]

        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        return str(data)[:500]


class MacDictatorApp:
    def __init__(self, hotkey: str, lazy: bool, no_tray: bool) -> None:
        self.lazy = lazy
        self.no_tray = no_tray
        self.recorder = AudioRecorder()
        self.transcriber = OpenRouterWhisperTranscriber()
        self.jobs: queue.Queue[Path | None] = queue.Queue()
        self.state_lock = threading.Lock()
        self.key_lock = threading.Lock()
        self.hotkey_lock = threading.Lock()
        self.pressed: set[str] = set()
        self.combo_down = False
        self.recording = False
        self.running = True
        self.icon: Any | None = None
        self.listener: keyboard.Listener | None = None
        self.hotkey_dialog_open = False
        self._apply_hotkey(hotkey)

    def _apply_hotkey(self, hotkey: str) -> None:
        hotkey = hotkey.strip().lower() or "f10"
        parts = {normalize_hotkey_part(part) for part in hotkey.split("+") if part.strip()}
        if not parts:
            parts = {"f10"}
            hotkey = "f10"
        self.hotkey = hotkey
        self.hotkey_parts = parts
        self.pressed.clear()
        self.combo_down = False
        print(f"Applied hotkey: {self.hotkey}")

    def run(self) -> None:
        print(f"Hotkey: {self.hotkey}")
        print("Hotkey mode: toggle")
        print("Press the hotkey to start recording. Press it again to transcribe and paste.")
        print("macOS requires Accessibility and Microphone permissions for your terminal/Python.")
        print(f"Frontmost app at startup: {describe_frontmost_app()}")

        worker = threading.Thread(target=self._worker_loop, daemon=True)
        worker.start()

        if not self.lazy:
            threading.Thread(target=self._safe_preload, daemon=True).start()

        self.listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self.listener.start()

        if self.no_tray:
            self.listener.join()
            return

        if not self._run_tray():
            self.listener.join()

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        with self.hotkey_lock:
            if self.hotkey_dialog_open:
                return
        names = key_names(key)
        with self.key_lock:
            self.pressed.update(names)
            is_match = self.hotkey_parts.issubset(self.pressed)
            if not is_match or self.combo_down:
                return
            self.combo_down = True

        print(f"Hotkey press event names={sorted(names)}")
        self.toggle()

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        with self.hotkey_lock:
            if self.hotkey_dialog_open:
                return
        names = key_names(key)
        is_hotkey_release = bool(self.hotkey_parts.intersection(names))
        with self.key_lock:
            self.pressed.difference_update(names)
            if not self.hotkey_parts.issubset(self.pressed):
                self.combo_down = False
        if is_hotkey_release:
            print(f"Hotkey release event names={sorted(names)}")

    def toggle(self) -> None:
        print("Hotkey toggle event")
        with self.state_lock:
            is_recording = self.recording
        if is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self) -> None:
        with self.state_lock:
            if self.recording:
                return
            self.recording = True
            print(f"Recording target app: {describe_frontmost_app()}")
            self.recorder.start()
            print("Recording...")
            self._set_status("Recording")

    def stop_recording(self) -> None:
        with self.state_lock:
            if not self.recording:
                return
            self.recording = False
            wav_path = self.recorder.stop_to_wav()

        self._set_status("Transcribing")
        if wav_path is not None:
            print(f"Queue transcription job path={wav_path}")
            self.jobs.put(wav_path)
        else:
            print("Recording too short or empty.")
            self._set_status("Ready")

    def quit(self) -> None:
        self.running = False
        if self.listener is not None:
            self.listener.stop()
        with self.state_lock:
            if self.recording:
                self.recording = False
                self.recorder.stop_to_wav()
        self.jobs.put(None)
        if self.icon is not None:
            self.icon.stop()

    def change_hotkey(self, hotkey: str) -> None:
        hotkey = hotkey.strip().lower()
        if not hotkey:
            raise ValueError("Hotkey is empty.")
        with self.state_lock:
            if self.recording:
                raise RuntimeError("Cannot change hotkey while recording.")
        previous = self.hotkey
        self._apply_hotkey(hotkey)
        set_env_value("DICTATOR_HOTKEY", hotkey)
        print(f"Hotkey changed: {previous} -> {hotkey}")
        self._set_status(f"Ready ({hotkey})")

    def open_hotkey_window(self) -> None:
        with self.hotkey_lock:
            if self.hotkey_dialog_open:
                print("Hotkey dialog is already open.")
                return
            self.hotkey_dialog_open = True
        threading.Thread(target=self._run_hotkey_window, daemon=True).start()

    def _run_hotkey_window(self) -> None:
        script_path = PROJECT_ROOT / "src" / "macos" / "hotkey_dialog.py"
        try:
            result = subprocess.run(
                [sys.executable, str(script_path), self.hotkey],
                capture_output=True,
                check=False,
                text=True,
            )
            if result.returncode == 0:
                hotkey = result.stdout.strip().splitlines()[-1].strip()
                print(f"Hotkey dialog captured: {hotkey}")
                self.change_hotkey(hotkey)
            else:
                stderr = result.stderr.strip()
                print(f"Hotkey dialog cancelled or failed: {stderr}")
        except Exception as exc:
            print(f"Hotkey dialog unavailable: {exc}", file=sys.stderr)
        finally:
            with self.hotkey_lock:
                self.hotkey_dialog_open = False

    def _worker_loop(self) -> None:
        while self.running:
            wav_path = self.jobs.get()
            if wav_path is None:
                return

            try:
                print(f"Transcribing {wav_path}")
                text = self.transcriber.transcribe(wav_path)
                if not text:
                    print("No text recognized.")
                    self._set_status("Ready")
                    continue

                print(f"Recognized: {text}")
                pyperclip.copy(text)
                print("Copied recognized text to clipboard")
                time.sleep(0.15)
                print(f"Frontmost before paste: {describe_frontmost_app()}")
                sent = send_command_v()
                print(f"Sent Command+V result: {sent}")
            except Exception as exc:
                print(f"Transcription failed: {exc}", file=sys.stderr)
            finally:
                self._set_status("Ready")

    def _safe_preload(self) -> None:
        try:
            self._set_status("Checking API key")
            self.transcriber.load()
        except Exception as exc:
            print(f"Transcription API check failed: {exc}", file=sys.stderr)
        finally:
            self._set_status("Ready")

    def _run_tray(self) -> bool:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception as exc:
            print(f"Tray disabled: {exc}", file=sys.stderr)
            return False

        def make_icon(color: tuple[int, int, int]) -> Any:
            icon_path = PROJECT_ROOT / "assets" / "icons" / "icon.png"
            if icon_path.exists():
                image = Image.open(icon_path).convert("RGBA")
                image.thumbnail((64, 64), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                x = (64 - image.width) // 2
                y = (64 - image.height) // 2
                canvas.alpha_composite(image, (x, y))
                image = canvas
            else:
                image = Image.new("RGBA", (64, 64), (24, 24, 24, 255))

            draw = ImageDraw.Draw(image)
            draw.ellipse((42, 42, 62, 62), fill=(24, 24, 24, 230))
            draw.ellipse((45, 45, 59, 59), fill=color)
            return image

        menu = pystray.Menu(
            pystray.MenuItem("Start/Stop dictation", lambda: self.toggle()),
            pystray.MenuItem("Hotkey...", lambda: self.open_hotkey_window()),
            pystray.MenuItem("Quit", lambda: self.quit()),
        )
        self.icon = pystray.Icon(
            "DictatorWhisper",
            make_icon((80, 190, 120)),
            "Dictator: Ready",
            menu,
        )
        self._make_icon = make_icon  # type: ignore[attr-defined]
        self.icon.run()
        return True

    def _set_status(self, status: str) -> None:
        print(f"Status: {status}")
        icon = self.icon
        if icon is None:
            return
        icon.title = f"Dictator: {status}"
        make_icon = getattr(self, "_make_icon", None)
        if make_icon is None:
            return
        if status == "Recording":
            icon.icon = make_icon((230, 80, 70))
        elif status == "Transcribing" or status == "Checking API key":
            icon.icon = make_icon((230, 180, 70))
        else:
            icon.icon = make_icon((80, 190, 120))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="macOS hotkey dictation with a configurable transcription API.")
    parser.add_argument(
        "--hotkey",
        default=os.environ.get("DICTATOR_HOTKEY", "f10"),
        help="Global toggle hotkey. Press once to record, press again to transcribe and paste.",
    )
    parser.add_argument("--lazy", action="store_true", help="Load API key on first transcription instead of startup.")
    parser.add_argument("--no-tray", action="store_true", help="Run without menu bar icon.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = MacDictatorApp(hotkey=args.hotkey, lazy=args.lazy, no_tray=args.no_tray)
    try:
        app.run()
    except KeyboardInterrupt:
        app.quit()


if __name__ == "__main__":
    main()
