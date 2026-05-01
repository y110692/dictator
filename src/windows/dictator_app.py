from __future__ import annotations

import argparse
import base64
import ctypes
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
SAMPLE_RATE = 16000
MIN_RECORDING_SECONDS = 3.0
HOTKEY_MONITOR_INTERVAL_SECONDS = 0.5
TOO_SHORT_STATUS_SECONDS = 1.2
OPENROUTER_CHAT_COMPLETIONS_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
OPENROUTER_MODEL = "openai/whisper-1"
OPENROUTER_LEGACY_CHAT_MODEL = "openai/gpt-audio-mini"
OPENROUTER_FALLBACK_MODEL = ""
DEFAULT_TRANSCRIPTION_PROMPT = "Transcribe this Russian speech to plain text. Return only the transcript."
DEFAULT_TRANSCRIPTION_LANGUAGE = "ru"
DEFAULT_TRANSCRIPTION_REFERER = "https://localhost/dictator"
DEFAULT_TRANSCRIPTION_TITLE = "Dictator"


SW_SHOW = 5
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_V = 0x56
VK_F10 = 0x79
VK_LWIN = 0x5B
VK_RWIN = 0x5C
MAPVK_VSC_TO_VK_EX = 3
TK_CTRL_MASK = 0x0004
TK_SHIFT_MASK = 0x0001
TK_ALT_MASK = 0x0008
TK_WIN_MASK = 0x0040


def normalize_tk_key(keysym: str) -> str:
    key = keysym.strip().lower()
    aliases = {
        "control_l": "ctrl",
        "control_r": "ctrl",
        "shift_l": "shift",
        "shift_r": "shift",
        "alt_l": "alt",
        "alt_r": "alt",
        "menu": "alt",
        "win_l": "windows",
        "win_r": "windows",
        "super_l": "windows",
        "super_r": "windows",
        "prior": "page up",
        "next": "page down",
        "return": "enter",
        "escape": "esc",
        "space": "space",
    }
    return aliases.get(key, key)


def is_vk_pressed(vk: int) -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def vk_from_scan_code(scan_code: Any) -> int | None:
    if os.name != "nt" or scan_code is None:
        return None
    try:
        vk = ctypes.windll.user32.MapVirtualKeyW(int(scan_code), MAPVK_VSC_TO_VK_EX)
    except Exception:
        return None
    return int(vk) if vk else None


def vk_from_key_name(key_name: str) -> int | None:
    key = key_name.strip().lower()
    named_keys = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "esc": 0x1B,
        "escape": 0x1B,
        "space": 0x20,
        "page up": 0x21,
        "page down": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "insert": 0x2D,
        "delete": 0x2E,
    }
    if key in named_keys:
        return named_keys[key]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit():
        number = int(key[1:])
        if 1 <= number <= 24:
            return 0x6F + number
    return None


def is_keyboard_event_still_pressed(event: Any, fallback_key_name: str) -> bool:
    vk = vk_from_scan_code(getattr(event, "scan_code", None))
    if vk is None:
        vk = vk_from_key_name(fallback_key_name)
    return bool(vk is not None and is_vk_pressed(vk))


def safe_keyboard_is_pressed(key_name: str) -> bool | None:
    try:
        return bool(key_name and keyboard.is_pressed(key_name))
    except Exception as exc:
        print(f"keyboard.is_pressed failed key={key_name!r}: {exc}", file=sys.stderr)
        return None


def hotkey_probe_line(label: str, hotkey: str, event: Any | None = None, scan_code: Any | None = None) -> str:
    event_name = getattr(event, "name", None) if event is not None else None
    event_scan_code = getattr(event, "scan_code", None) if event is not None else None
    effective_scan_code = event_scan_code if event_scan_code is not None else scan_code
    scan_vk = vk_from_scan_code(effective_scan_code)
    name_vk = vk_from_key_name(str(event_name or hotkey))
    hotkey_vk = vk_from_key_name(hotkey)
    scan_vk_pressed = is_vk_pressed(scan_vk) if scan_vk is not None else None
    name_vk_pressed = is_vk_pressed(name_vk) if name_vk is not None else None
    hotkey_vk_pressed = is_vk_pressed(hotkey_vk) if hotkey_vk is not None else None
    keyboard_event_name_pressed = safe_keyboard_is_pressed(str(event_name)) if event_name else None
    keyboard_hotkey_pressed = safe_keyboard_is_pressed(hotkey)
    return (
        f"{label} "
        f"hotkey={hotkey!r} event_name={event_name!r} event_scan_code={event_scan_code!r} "
        f"probe_scan_code={effective_scan_code!r} scan_vk={scan_vk!r} name_vk={name_vk!r} hotkey_vk={hotkey_vk!r} "
        f"win32_scan_pressed={scan_vk_pressed!r} win32_name_pressed={name_vk_pressed!r} "
        f"win32_hotkey_pressed={hotkey_vk_pressed!r} keyboard_event_name_pressed={keyboard_event_name_pressed!r} "
        f"keyboard_hotkey_pressed={keyboard_hotkey_pressed!r}"
    )


def hotkey_probe_any_pressed(hotkey: str, event: Any | None = None, scan_code: Any | None = None) -> bool:
    event_name = getattr(event, "name", None) if event is not None else None
    event_scan_code = getattr(event, "scan_code", None) if event is not None else None
    effective_scan_code = event_scan_code if event_scan_code is not None else scan_code
    scan_vk = vk_from_scan_code(effective_scan_code)
    name_vk = vk_from_key_name(str(event_name or hotkey))
    hotkey_vk = vk_from_key_name(hotkey)
    checks = [
        is_vk_pressed(scan_vk) if scan_vk is not None else False,
        is_vk_pressed(name_vk) if name_vk is not None else False,
        is_vk_pressed(hotkey_vk) if hotkey_vk is not None else False,
        bool(safe_keyboard_is_pressed(str(event_name))) if event_name else False,
        bool(safe_keyboard_is_pressed(hotkey)),
    ]
    return any(checks)


def get_modifier_parts(state: int, prefer_physical: bool = True) -> list[str]:
    if prefer_physical and os.name == "nt":
        parts: list[str] = []
        if is_vk_pressed(VK_CONTROL):
            parts.append("ctrl")
        if is_vk_pressed(VK_MENU):
            parts.append("alt")
        if is_vk_pressed(VK_SHIFT):
            parts.append("shift")
        if is_vk_pressed(VK_LWIN) or is_vk_pressed(VK_RWIN):
            parts.append("windows")
        return parts

    parts = []
    if state & TK_CTRL_MASK:
        parts.append("ctrl")
    if state & TK_ALT_MASK:
        parts.append("alt")
    if state & TK_SHIFT_MASK:
        parts.append("shift")
    if state & TK_WIN_MASK:
        parts.append("windows")
    return parts


def format_hotkey_from_tk_event(keysym: str, state: int, prefer_physical: bool = True) -> str | None:
    key = normalize_tk_key(keysym)
    if not key or key in {"ctrl", "shift", "alt", "windows"}:
        return None

    parts = get_modifier_parts(state, prefer_physical=prefer_physical)

    if key not in parts:
        parts.append(key)
    return "+".join(parts)


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


def setup_log_file() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log_path = Path(os.environ.get("DICTATOR_LOG_FILE", RUNTIME_DIR / "dictator.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = TimestampedTee(sys.stdout, log_file, "stdout")  # type: ignore[assignment]
    sys.stderr = TimestampedTee(sys.stderr, log_file, "stderr")  # type: ignore[assignment]
    print("")
    print(f"--- Dictator started, pid={os.getpid()}, log={log_path} ---")


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


load_env_file()
setup_log_file()

import keyboard
import numpy as np
import pyperclip
import requests
import sounddevice as sd
import soundfile as sf


def get_foreground_window_handle() -> int | None:
    if os.name != "nt":
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None
    return int(hwnd) if hwnd else None


def describe_window(hwnd: int | None = None) -> str:
    if os.name != "nt":
        return "window=unsupported"

    if hwnd is None:
        hwnd = get_foreground_window_handle()
    if not hwnd:
        return "hwnd=None"

    try:
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return f"hwnd={hwnd} pid={pid.value} title={buffer.value!r}"
    except Exception as exc:
        return f"hwnd={hwnd} describe_failed={exc}"


def restore_foreground_window(hwnd: int | None) -> bool:
    if os.name != "nt" or not hwnd:
        return False

    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            return False
        user32.ShowWindow(hwnd, SW_SHOW)
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception as exc:
        print(f"Restore foreground failed: {exc}", file=sys.stderr)
        return False


def release_paste_related_keys() -> None:
    if os.name != "nt":
        return
    try:
        user32 = ctypes.windll.user32
        for vk in (VK_V, VK_CONTROL, VK_SHIFT, VK_MENU, VK_F10):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        print(f"Release paste keys failed: {exc}", file=sys.stderr)


def send_ctrl_v() -> bool:
    release_paste_related_keys()
    if os.name != "nt":
        keyboard.send("ctrl+v")
        return True

    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.04)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception as exc:
        print(f"Win32 Ctrl+V failed, retrying via keyboard.send: {exc}", file=sys.stderr)
        keyboard.send("ctrl+v")
        return True


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
                            {
                                "type": "text",
                                "text": self.prompt,
                            },
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_data,
                                    "format": "wav",
                                },
                            },
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


class DictatorApp:
    def __init__(self, hotkey: str, lazy: bool, no_tray: bool, suppress_hotkey: bool) -> None:
        self.hotkey = hotkey
        self.lazy = lazy
        self.no_tray = no_tray
        self.suppress_hotkey = suppress_hotkey
        self.recorder = AudioRecorder()
        self.transcriber = OpenRouterWhisperTranscriber()
        self.jobs: queue.Queue[Path | None] = queue.Queue()
        self.state_lock = threading.Lock()
        self.status_lock = threading.Lock()
        self.status = "Ready"
        self.status_generation = 0
        self.recording = False
        self.running = True
        self.icon: Any | None = None
        self.recording_target_hwnd: int | None = None
        self.recording_started_at: float | None = None
        self.recording_hotkey_name: str | None = None
        self.recording_hotkey_scan_code: Any | None = None
        self.recording_monitor_stop = threading.Event()
        self.hotkey_down = False
        self.ignored_press_repeat_count = 0
        self.last_ignored_press_log_at = 0.0
        self.hotkey_hooks: list[tuple[str, Any]] = []
        self.hotkey_lock = threading.Lock()
        self.hotkey_dialog_open = False

    def run(self) -> None:
        print(f"Hotkey: {self.hotkey}")
        print(f"Suppress hotkey in target app: {self.suppress_hotkey}")
        print("Press the hotkey to start recording. Press it again to transcribe and paste.")
        print(f"Python executable: {sys.executable}")
        print(f"Minimum recording duration before transcription: {MIN_RECORDING_SECONDS:.2f}s")
        print(f"Hotkey monitor interval: {HOTKEY_MONITOR_INTERVAL_SECONDS:.2f}s")

        worker = threading.Thread(target=self._worker_loop, daemon=True)
        worker.start()

        if not self.lazy:
            threading.Thread(target=self._safe_preload, daemon=True).start()

        self._register_hotkey(self.hotkey)

        if self.no_tray:
            keyboard.wait()
            return

        if not self._run_tray():
            keyboard.wait()

    def _register_hotkey(self, hotkey: str) -> None:
        with self.hotkey_lock:
            self._unregister_hotkey_locked()
            if "+" in hotkey:
                handle = keyboard.add_hotkey(hotkey, self.toggle, suppress=self.suppress_hotkey)
                self.hotkey_hooks.append(("hotkey", handle))
            else:
                keyboard.on_press_key(
                    hotkey,
                    lambda event: self._on_hotkey_press(event),
                    suppress=self.suppress_hotkey,
                )
                keyboard.on_release_key(
                    hotkey,
                    lambda event: self._on_hotkey_release(event),
                    suppress=self.suppress_hotkey,
                )
                self.hotkey_hooks.append(("key", hotkey))
            self.hotkey = hotkey
            print(f"Registered toggle hotkey: {self.hotkey}")

    def _unregister_hotkey_locked(self) -> None:
        for kind, handle in self.hotkey_hooks:
            try:
                if kind == "hotkey":
                    keyboard.remove_hotkey(handle)
                elif kind == "key":
                    keyboard.unhook_key(handle)
                else:
                    keyboard.unhook(handle)
            except Exception as exc:
                print(f"Failed to unregister hotkey hook: {exc}", file=sys.stderr)
        self.hotkey_hooks = []
        self.hotkey_down = False

    def change_hotkey(self, hotkey: str) -> None:
        hotkey = hotkey.strip().lower()
        if not hotkey:
            raise ValueError("Hotkey is empty.")
        with self.state_lock:
            if self.recording:
                raise RuntimeError("Cannot change hotkey while recording.")
        previous = self.hotkey
        try:
            self._register_hotkey(hotkey)
        except Exception:
            if previous:
                try:
                    self._register_hotkey(previous)
                except Exception as restore_exc:
                    print(f"Failed to restore previous hotkey {previous}: {restore_exc}", file=sys.stderr)
            raise
        set_env_value("DICTATOR_HOTKEY", hotkey)
        print(f"Hotkey changed: {previous} -> {hotkey}")
        self._set_status(f"Ready ({hotkey})")

    def toggle(self, event: Any | None = None, reason: str = "toggle") -> None:
        print("Hotkey toggle event")
        with self.state_lock:
            is_recording = self.recording
        if is_recording:
            self.stop_recording(event=event, reason=reason)
        else:
            self.start_recording(event=event, reason=reason)

    def _on_hotkey_press(self, event: Any) -> None:
        with self.state_lock:
            if self.hotkey_down:
                self.ignored_press_repeat_count += 1
                now = time.monotonic()
                if now - self.last_ignored_press_log_at >= 1.0:
                    self.last_ignored_press_log_at = now
                    print(
                        f"Hotkey press autorepeat ignored count={self.ignored_press_repeat_count} "
                        f"name={getattr(event, 'name', None)} scan_code={getattr(event, 'scan_code', None)}"
                    )
                return
            self.hotkey_down = True
        self.ignored_press_repeat_count = 0
        print(hotkey_probe_line("Hotkey press probe", self.hotkey, event=event))
        print(f"Hotkey press event name={getattr(event, 'name', None)} scan_code={getattr(event, 'scan_code', None)}")
        self.toggle(event=event, reason="hotkey")

    def _on_hotkey_release(self, event: Any) -> None:
        with self.state_lock:
            self.hotkey_down = False
        print(f"Hotkey release event name={getattr(event, 'name', None)} scan_code={getattr(event, 'scan_code', None)}")

    def start_recording(self, event: Any | None = None, reason: str = "manual") -> None:
        with self.state_lock:
            if self.recording:
                return
            self.recording = True
            self.recording_started_at = time.monotonic()
            self.recording_hotkey_name = getattr(event, "name", None) if event is not None else self.hotkey
            self.recording_hotkey_scan_code = getattr(event, "scan_code", None) if event is not None else None
            self.recording_target_hwnd = get_foreground_window_handle()
            self.recording_monitor_stop.clear()
            self.ignored_press_repeat_count = 0
            self.last_ignored_press_log_at = 0.0
            print(
                f"Recording start reason={reason} hotkey={self.hotkey!r} "
                f"event_name={self.recording_hotkey_name!r} event_scan_code={self.recording_hotkey_scan_code!r}"
            )
            print(f"Recording target window: {describe_window(self.recording_target_hwnd)}")
            print(hotkey_probe_line("Recording start probe", self.hotkey, event=event, scan_code=self.recording_hotkey_scan_code))
            self.recorder.start()
            threading.Thread(target=self._monitor_hotkey_state, args=(self.recording_started_at,), daemon=True).start()
            print("Recording...")
            self._set_status("Recording")

    def stop_recording(self, event: Any | None = None, reason: str = "manual") -> None:
        with self.state_lock:
            if not self.recording:
                print(f"Stop recording ignored reason={reason}; recording is not active.")
                return
            self.recording = False
            self.recording_monitor_stop.set()
            started_at = self.recording_started_at
            duration = time.monotonic() - started_at if started_at is not None else 0.0
            print(
                f"Recording stop reason={reason} duration={duration:.3f}s "
                f"min_required={MIN_RECORDING_SECONDS:.3f}s"
            )
            print(hotkey_probe_line("Recording stop probe", self.hotkey, event=event, scan_code=self.recording_hotkey_scan_code))
            wav_path = self.recorder.stop_to_wav()
            self.recording_started_at = None
            self.recording_hotkey_name = None
            self.recording_hotkey_scan_code = None

        if duration < MIN_RECORDING_SECONDS:
            if wav_path is not None:
                print(f"Discarding recording shorter than minimum path={wav_path} duration={duration:.3f}s")
            else:
                print(f"Discarding empty recording shorter than minimum duration={duration:.3f}s")
            generation = self._set_status("Too short")
            self._schedule_ready_after_too_short(generation)
            return

        if wav_path is not None:
            self._set_status("Transcribing")
            print(f"Queue transcription job path={wav_path}")
            self.jobs.put(wav_path)
        else:
            print("Recording too short or empty.")
            self._set_status("Ready")

    def _monitor_hotkey_state(self, monitor_started_at: float | None) -> None:
        tick = 0
        while not self.recording_monitor_stop.wait(HOTKEY_MONITOR_INTERVAL_SECONDS):
            with self.state_lock:
                if not self.recording or self.recording_started_at != monitor_started_at:
                    return
                started_at = self.recording_started_at
                scan_code = self.recording_hotkey_scan_code
            elapsed = time.monotonic() - started_at if started_at is not None else 0.0
            tick += 1
            print(
                f"Hotkey monitor tick={tick} elapsed={elapsed:.3f}s "
                f"{hotkey_probe_line('state', self.hotkey, scan_code=scan_code)}"
            )

    def _schedule_ready_after_too_short(self, generation: int) -> None:
        def reset_if_still_too_short() -> None:
            time.sleep(TOO_SHORT_STATUS_SECONDS)
            with self.status_lock:
                should_reset = self.status == "Too short" and self.status_generation == generation
            if should_reset:
                print(f"Too short status elapsed {TOO_SHORT_STATUS_SECONDS:.1f}s; returning to Ready.")
                self._set_status("Ready")

        threading.Thread(target=reset_if_still_too_short, daemon=True).start()

    def quit(self) -> None:
        self.running = False
        self.recording_monitor_stop.set()
        with self.hotkey_lock:
            self._unregister_hotkey_locked()
        with self.state_lock:
            if self.recording:
                self.recording = False
                self.recorder.stop_to_wav()
        self.jobs.put(None)
        if self.icon is not None:
            self.icon.stop()

    def open_hotkey_window(self) -> None:
        with self.hotkey_lock:
            if self.hotkey_dialog_open:
                print("Hotkey dialog is already open.")
                return
            self.hotkey_dialog_open = True
        threading.Thread(target=self._run_hotkey_window, daemon=True).start()

    def _run_hotkey_window(self) -> None:
        try:
            import tkinter as tk
            from tkinter import messagebox
        except Exception as exc:
            print(f"Hotkey dialog unavailable: {exc}", file=sys.stderr)
            with self.hotkey_lock:
                self.hotkey_dialog_open = False
            return

        captured = {"value": ""}
        saved = {"value": False}
        suspended_hotkey = self.hotkey

        with self.hotkey_lock:
            self._unregister_hotkey_locked()
        print(f"Hotkey capture dialog opened; suspended hotkey: {suspended_hotkey}")

        def close() -> None:
            if not saved["value"] and self.running:
                try:
                    self._register_hotkey(suspended_hotkey)
                except Exception as exc:
                    print(f"Failed to restore hotkey after dialog close: {exc}", file=sys.stderr)
            with self.hotkey_lock:
                self.hotkey_dialog_open = False
            root.destroy()

        def on_key_press(event: Any) -> str:
            hotkey = format_hotkey_from_tk_event(str(event.keysym), int(event.state))
            print(f"Hotkey dialog key event keysym={event.keysym} state={int(event.state)} captured={hotkey}")
            if hotkey is None:
                status_var.set("Зажмите Ctrl/Alt/Shift/Win и нажмите основную клавишу")
                return "break"
            captured["value"] = hotkey
            hotkey_var.set(hotkey)
            status_var.set("Нажмите «Сохранить», чтобы применить")
            return "break"

        def save() -> None:
            hotkey = captured["value"].strip()
            if not hotkey:
                messagebox.showwarning("Hotkey", "Нажмите новую клавишу или комбинацию.")
                return
            try:
                self.change_hotkey(hotkey)
            except Exception as exc:
                messagebox.showerror("Hotkey", f"Не удалось применить hotkey:\n{exc}")
                return
            saved["value"] = True
            close()

        root = tk.Tk()
        root.title("Dictator: горячая клавиша")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", close)

        frame = tk.Frame(root, padx=18, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Нажмите новую горячую клавишу", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(frame, text=f"Текущая: {self.hotkey}", fg="#555555").pack(anchor="w", pady=(4, 10))

        hotkey_var = tk.StringVar(value="ожидание...")
        hotkey_label = tk.Label(
            frame,
            textvariable=hotkey_var,
            font=("Segoe UI", 18, "bold"),
            width=22,
            relief="solid",
            bd=1,
            padx=8,
            pady=8,
        )
        hotkey_label.pack(fill="x")

        status_var = tk.StringVar(value="Например: F9 или Ctrl+Alt+Space")
        tk.Label(frame, textvariable=status_var, fg="#555555", wraplength=320).pack(anchor="w", pady=(8, 14))

        buttons = tk.Frame(frame)
        buttons.pack(fill="x")
        tk.Button(buttons, text="Сохранить", width=12, command=save).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="Отмена", width=10, command=close).pack(side="right")

        root.bind("<KeyPress>", on_key_press)
        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x = max(0, (root.winfo_screenwidth() - width) // 2)
        y = max(0, (root.winfo_screenheight() - height) // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.lift()
        root.focus_force()
        try:
            if os.name == "nt":
                ctypes.windll.user32.SetForegroundWindow(root.winfo_id())
        except Exception as exc:
            print(f"Hotkey dialog focus failed: {exc}", file=sys.stderr)
        root.mainloop()

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
                time.sleep(0.1)
                print(f"Foreground before paste: {describe_window()}")
                print(f"Recorded target before paste: {describe_window(self.recording_target_hwnd)}")
                restored = restore_foreground_window(self.recording_target_hwnd)
                print(f"Restore recorded target result: {restored}")
                time.sleep(0.1)
                sent = send_ctrl_v()
                print(f"Sent Ctrl+V result: {sent}")
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
                draw.ellipse((12, 8, 52, 48), fill=color)
                draw.rectangle((28, 44, 36, 56), fill=color)
                draw.rectangle((20, 54, 44, 60), fill=color)
                return image

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

    def _set_status(self, status: str) -> int:
        with self.status_lock:
            self.status = status
            self.status_generation += 1
            generation = self.status_generation
        print(f"Status: {status}")
        icon = self.icon
        if icon is None:
            return generation
        icon.title = f"Dictator: {status}"
        make_icon = getattr(self, "_make_icon", None)
        if make_icon is None:
            return generation
        if status == "Recording":
            icon.icon = make_icon((230, 80, 70))
        elif status == "Transcribing" or status == "Checking API key":
            icon.icon = make_icon((230, 180, 70))
        elif status == "Too short":
            icon.icon = make_icon((245, 245, 245))
        else:
            icon.icon = make_icon((80, 190, 120))
        return generation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows hotkey dictation with a configurable transcription API.")
    parser.add_argument(
        "--hotkey",
        default=os.environ.get("DICTATOR_HOTKEY", "f10"),
        help="Global toggle hotkey. Press once to record, press again to transcribe and paste.",
    )
    parser.add_argument("--lazy", action="store_true", help="Load model on first transcription instead of startup.")
    parser.add_argument("--no-tray", action="store_true", help="Run without tray icon.")
    parser.add_argument(
        "--allow-hotkey-through",
        action="store_true",
        help="Deprecated: hotkey passthrough is now the default.",
    )
    parser.add_argument(
        "--suppress-hotkey",
        action="store_true",
        help="Suppress the dictation hotkey in the focused application. Can interfere with keyboard input.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = DictatorApp(
        hotkey=args.hotkey,
        lazy=args.lazy,
        no_tray=args.no_tray,
        suppress_hotkey=args.suppress_hotkey,
    )
    try:
        app.run()
    except KeyboardInterrupt:
        app.quit()


if __name__ == "__main__":
    main()
