from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


class CredentialStoreError(RuntimeError):
    """A protected local credential could not be stored or loaded safely."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


@dataclass(frozen=True)
class CredentialStatus:
    present: bool
    protected_for_current_user: bool
    path: str

    def safe_summary(self) -> dict[str, object]:
        return {
            "present": self.present,
            "protected_for_current_user": self.protected_for_current_user,
            "path": self.path,
        }


def default_p1s_credential_path(environ: dict[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    local = values.get("LOCALAPPDATA")
    if not local:
        raise CredentialStoreError("LOCALAPPDATA is unavailable")
    return Path(local) / "THS-Command-Center" / "secrets" / "p1s-access-code.dpapi"


def store_p1s_access_code(secret: str, path: Path | None = None) -> CredentialStatus:
    if not secret or not secret.strip():
        raise CredentialStoreError("access code cannot be empty")
    target = Path(path) if path is not None else default_p1s_credential_path()
    protected = _protect(secret.encode("utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        temporary.write_bytes(protected)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        _restrict_windows_acl(target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise CredentialStoreError("protected credential could not be written") from exc
    return credential_status(target)


def load_p1s_access_code(path: Path | None = None) -> str:
    target = Path(path) if path is not None else default_p1s_credential_path()
    try:
        protected = target.read_bytes()
    except OSError as exc:
        raise CredentialStoreError("protected credential is missing or unreadable") from exc
    try:
        return _unprotect(protected).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CredentialStoreError(
            "protected credential cannot be decrypted by the current Windows user"
        ) from exc


def credential_status(path: Path | None = None) -> CredentialStatus:
    target = Path(path) if path is not None else default_p1s_credential_path()
    present = target.is_file()
    protected = False
    if present:
        try:
            _unprotect(target.read_bytes())
            protected = True
        except (CredentialStoreError, OSError):
            protected = False
    return CredentialStatus(present, protected, str(target))


def _protect(value: bytes) -> bytes:
    return _crypt(value, decrypt=False)


def _unprotect(value: bytes) -> bytes:
    return _crypt(value, decrypt=True)


def _crypt(value: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise CredentialStoreError("Windows DPAPI is required")
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if decrypt:
        result = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
        )
    else:
        result = crypt32.CryptProtectData(
            ctypes.byref(source), "THS P1S credential", None, None, None, 1, ctypes.byref(output)
        )
    if not result:
        action = "decrypt" if decrypt else "protect"
        raise CredentialStoreError(f"Windows could not {action} the local credential")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def _restrict_windows_acl(path: Path) -> None:
    identity = _windows_identity()
    if os.name != "nt" or not identity:
        return
    result = subprocess.run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{identity}:(F)",
            "/grant:r",
            "SYSTEM:(F)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CredentialStoreError("Windows credential file permissions could not be restricted")


def _windows_identity() -> str | None:
    if os.name != "nt":
        return None
    name = ctypes.create_unicode_buffer(256)
    size = wintypes.DWORD(len(name))
    if not ctypes.windll.advapi32.GetUserNameW(name, ctypes.byref(size)):
        return None
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{name.value}" if domain else name.value
