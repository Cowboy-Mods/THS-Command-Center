from __future__ import annotations

from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parent.parent
UTILITY = ROOT / "scripts" / "configure-elevenlabs-credential.py"
source = UTILITY.read_text(encoding="utf-8")
tree = ast.parse(source)

assert "getpass" not in source
assert 'choices=("set-gui", "demo-mask", "status", "remove")' in source
assert "show=MASK" in source and 'MASK = "●"' in source
assert "secrets.token_urlsafe(24)" in source
assert "credential_write(secret)" in source
assert "credential_write" not in source.split("if demonstration:", 1)[1].split("else:", 1)[0]
assert all(value not in source for value in ("subprocess", "powershell", "cmd.exe", "shell=True", "clipboard", "os.environ"))
assert all(value not in source for value in ("print(secret", "repr(secret", "len(secret)", "hashlib", "fingerprint"))
assert 'messagebox.showinfo(TITLE, "SUCCESS"' in source
assert source.count('messagebox.showerror(TITLE, "FAILED"') == 2
assert 'value.set("")' in source and "secret = None" in source
assert "credential_read()" in source and 'print("PRESENT" if credential_read() else "MISSING")' in source
print("ELEVENLABS_CREDENTIAL_GUI_STATIC_QA=PASS real_key=0 network=0 storage=0")
