"""Configure Maeve's restricted ElevenLabs key with a native masked GUI."""

from __future__ import annotations

import argparse
from pathlib import Path
import secrets
import sys
import tkinter as tk
from tkinter import messagebox

BROKER = Path(__file__).resolve().parent.parent / "broker"
sys.path.insert(0, str(BROKER))
from voice_provider import credential_read, credential_remove, credential_write  # noqa: E402


TITLE = "Maeve — ElevenLabs Credential"
MASK = "●"


def build_window(*, demonstration: bool) -> tuple[tk.Tk, tk.Entry, tk.StringVar]:
    root = tk.Tk()
    root.title(TITLE + (" — Masking Demonstration" if demonstration else ""))
    root.resizable(False, False)
    root.attributes("-topmost", True)
    frame = tk.Frame(root, padx=24, pady=20)
    frame.pack()
    heading = "NONSECRET MASKING DEMONSTRATION" if demonstration else "Restricted ElevenLabs API key"
    tk.Label(frame, text=heading, font=("Segoe UI", 11, "bold")).pack(anchor="w")
    detail = ("The generated canary below is not a credential and will not be stored."
              if demonstration else
              "Enter the restricted key locally. It will be stored only in Windows Credential Manager.")
    tk.Label(frame, text=detail, font=("Segoe UI", 9), wraplength=430, justify="left").pack(anchor="w", pady=(4, 12))
    value = tk.StringVar(root, "")
    entry = tk.Entry(frame, textvariable=value, show=MASK, width=52, font=("Consolas", 11), exportselection=False)
    entry.pack(fill="x")
    status = tk.Label(frame, text="MASKED FIELD — CONTENT NOT DISPLAYED", fg="#a64b00", font=("Segoe UI", 9, "bold"))
    status.pack(anchor="w", pady=(8, 12))
    buttons = tk.Frame(frame); buttons.pack(fill="x")
    if demonstration:
        value.set(secrets.token_urlsafe(24))
        tk.Button(buttons, text="Close demonstration", command=root.destroy, width=22).pack(side="right")
    else:
        outcome = {"done": False}
        def cancel() -> None:
            value.set(""); outcome["done"] = True; root.destroy()
        def save() -> None:
            secret = value.get()
            value.set("")
            if len(secret.strip()) < 20:
                secret = None
                messagebox.showerror(TITLE, "FAILED", parent=root)
                return
            try:
                credential_write(secret)
                secret = None
                outcome["done"] = True
                messagebox.showinfo(TITLE, "SUCCESS", parent=root)
                root.destroy()
            except Exception:
                secret = None
                messagebox.showerror(TITLE, "FAILED", parent=root)
        tk.Button(buttons, text="Cancel", command=cancel, width=12).pack(side="right")
        tk.Button(buttons, text="Store securely", command=save, width=16).pack(side="right", padx=(0, 8))
        root.protocol("WM_DELETE_WINDOW", cancel)
    entry.focus_set()
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - root.winfo_reqwidth()) // 2)
    y = max(0, (root.winfo_screenheight() - root.winfo_reqheight()) // 3)
    root.geometry(f"+{x}+{y}")
    return root, entry, value


def run_gui(*, demonstration: bool) -> None:
    root, _entry, value = build_window(demonstration=demonstration)
    try:
        root.mainloop()
    finally:
        value.set("")
        _entry = None
        value = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Maeve ElevenLabs credential utility")
    parser.add_argument("action", choices=("set-gui", "demo-mask", "status", "remove"))
    args = parser.parse_args()
    if args.action == "set-gui":
        run_gui(demonstration=False)
    elif args.action == "demo-mask":
        run_gui(demonstration=True)
    elif args.action == "remove":
        credential_remove()
        print("REMOVED")
    else:
        print("PRESENT" if credential_read() else "MISSING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
