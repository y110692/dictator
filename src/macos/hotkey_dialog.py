from __future__ import annotations

import sys
from typing import Any


TK_SHIFT_MASK = 0x0001
TK_CTRL_MASK = 0x0004
TK_ALT_MASK = 0x0008
TK_CMD_MASK = 0x0010


def normalize_tk_key(keysym: str) -> str:
    key = keysym.strip().lower()
    aliases = {
        "command": "cmd",
        "command_l": "cmd",
        "command_r": "cmd",
        "meta_l": "cmd",
        "meta_r": "cmd",
        "control_l": "ctrl",
        "control_r": "ctrl",
        "shift_l": "shift",
        "shift_r": "shift",
        "option_l": "alt",
        "option_r": "alt",
        "alt_l": "alt",
        "alt_r": "alt",
        "return": "enter",
        "escape": "esc",
        "space": "space",
    }
    return aliases.get(key, key)


def format_hotkey_from_tk_event(keysym: str, state: int) -> str | None:
    key = normalize_tk_key(keysym)
    if not key or key in {"cmd", "ctrl", "alt", "shift"}:
        return None

    parts: list[str] = []
    if state & TK_CMD_MASK:
        parts.append("cmd")
    if state & TK_CTRL_MASK:
        parts.append("ctrl")
    if state & TK_ALT_MASK:
        parts.append("alt")
    if state & TK_SHIFT_MASK:
        parts.append("shift")

    if key not in parts:
        parts.append(key)
    return "+".join(parts)


def main() -> None:
    import tkinter as tk
    from tkinter import messagebox

    current_hotkey = sys.argv[1] if len(sys.argv) > 1 else "f10"
    captured = {"value": ""}

    def close(code: int = 1) -> None:
        root.destroy()
        raise SystemExit(code)

    def on_key_press(event: Any) -> str:
        hotkey = format_hotkey_from_tk_event(str(event.keysym), int(event.state))
        if hotkey is None:
            status_var.set("Hold Command/Control/Option/Shift and press a main key")
            return "break"
        captured["value"] = hotkey
        hotkey_var.set(hotkey)
        status_var.set("Click Save to apply")
        return "break"

    def save() -> None:
        hotkey = captured["value"].strip()
        if not hotkey:
            messagebox.showwarning("Hotkey", "Press a key or key combination first.")
            return
        print(hotkey, flush=True)
        close(0)

    root = tk.Tk()
    root.title("Dictator: Hotkey")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.protocol("WM_DELETE_WINDOW", lambda: close(1))

    frame = tk.Frame(root, padx=18, pady=16)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text="Press a new hotkey", font=("Arial", 13, "bold")).pack(anchor="w")
    tk.Label(frame, text=f"Current: {current_hotkey}", fg="#555555").pack(anchor="w", pady=(4, 10))

    hotkey_var = tk.StringVar(value="waiting...")
    hotkey_label = tk.Label(
        frame,
        textvariable=hotkey_var,
        font=("Arial", 22, "bold"),
        width=22,
        relief="solid",
        bd=1,
        padx=8,
        pady=8,
    )
    hotkey_label.pack(fill="x")

    status_var = tk.StringVar(value="Example: F9 or Cmd+Shift+D")
    tk.Label(frame, textvariable=status_var, fg="#555555", wraplength=320).pack(anchor="w", pady=(8, 14))

    buttons = tk.Frame(frame)
    buttons.pack(fill="x")
    tk.Button(buttons, text="Save", width=12, command=save).pack(side="right", padx=(8, 0))
    tk.Button(buttons, text="Cancel", width=10, command=lambda: close(1)).pack(side="right")

    root.bind("<KeyPress>", on_key_press)
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.lift()
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
