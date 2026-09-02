"""Explicit Maeve voice providers, credential access, and content-free usage accounting."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave


ELEVENLABS_API = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = "eleven_flash_v2_5"
ELEVENLABS_VOICE_ID = "uQQ5hr5j8TOzHNkY0VtG"
ELEVENLABS_VOICE_NAME = "Maeve - Dublin Command"
ELEVENLABS_OUTPUT_FORMAT = "pcm_24000"
ELEVENLABS_SPEED = 0.90
SAMPLE_RATE = 24_000
MAX_TEXT_CHARS = 2_000
MAX_AUDIO_BYTES = 8 * 1024 * 1024
CREDENTIAL_TARGET = "MaeveV2/ElevenLabsPrimary"
DEFAULT_MONTHLY_CEILING = 2_000
DEFAULT_SESSION_CEILING = 2_000
DEFAULT_WARNING_THRESHOLD = 1_600


class ProviderFailure(RuntimeError):
    """Content-free provider failure safe to map to a bounded UI state."""


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


def _credential_api():
    if os.name != "nt":
        raise ProviderFailure("Windows Credential Manager unavailable")
    api = ctypes.WinDLL("Advapi32.dll")
    api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    return api


def credential_write(secret: str) -> None:
    if not isinstance(secret, str) or len(secret.strip()) < 20:
        raise ProviderFailure("Credential rejected")
    encoded = secret.strip().encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    record = _CREDENTIALW(Type=1, TargetName=CREDENTIAL_TARGET,
                          CredentialBlobSize=len(encoded), CredentialBlob=blob,
                          Persist=2, UserName="Maeve ElevenLabs restricted key")
    if not _credential_api().CredWriteW(ctypes.byref(record), 0):
        raise ProviderFailure("Credential write failed")


def credential_read() -> str | None:
    pointer = ctypes.POINTER(_CREDENTIALW)()
    api = _credential_api()
    if not api.CredReadW(CREDENTIAL_TARGET, 1, 0, ctypes.byref(pointer)):
        return None
    try:
        record = pointer.contents
        raw = ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
        value = raw.decode("utf-16-le")
        return value if len(value) >= 20 else None
    finally:
        api.CredFree(pointer)


def credential_remove() -> bool:
    api = _credential_api()
    if api.CredDeleteW(CREDENTIAL_TARGET, 1, 0):
        return True
    return credential_read() is None


@dataclass(frozen=True)
class UsageLimits:
    monthly: int = DEFAULT_MONTHLY_CEILING
    session: int = DEFAULT_SESSION_CEILING
    warning: int = DEFAULT_WARNING_THRESHOLD

    def validate(self) -> None:
        if not (1 <= self.warning <= self.monthly and 1 <= self.session <= self.monthly):
            raise ProviderFailure("Usage configuration rejected")


class UsageLedger:
    """Persists counts/status only; never text, audio, identities, or credentials."""

    def __init__(self, path: Path, limits: UsageLimits = UsageLimits()) -> None:
        limits.validate()
        self.path, self.limits = path, limits
        self.lock = threading.Lock()
        self.session_characters = 0

    @staticmethod
    def _month() -> str:
        return time.strftime("%Y-%m")

    def _read(self) -> dict[str, object]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if not isinstance(value, dict) or value.get("month") != self._month():
            return {"month": self._month(), "requests": 0, "characters": 0,
                    "successful": 0, "failed": 0, "canceled": 0}
        allowed = {"month", "requests", "characters", "successful", "failed", "canceled"}
        return {key: value.get(key, 0) for key in allowed}

    def _write(self, value: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.path)

    def authorize(self, characters: int) -> dict[str, object]:
        if characters < 1 or characters > MAX_TEXT_CHARS:
            raise ProviderFailure("Voice text length rejected")
        with self.lock:
            state = self._read()
            monthly = int(state["characters"])
            if monthly + characters > self.limits.monthly or self.session_characters + characters > self.limits.session:
                raise ProviderFailure("VOICE_USAGE_LIMIT_REACHED")
            return {"monthlyCharacters": monthly, "sessionCharacters": self.session_characters,
                    "warning": monthly + characters >= self.limits.warning,
                    "monthlyCeiling": self.limits.monthly, "sessionCeiling": self.limits.session}

    def record(self, characters: int, status: str) -> None:
        if status not in {"successful", "failed", "canceled"}:
            raise ProviderFailure("Usage status rejected")
        with self.lock:
            state = self._read()
            state["requests"] = int(state["requests"]) + 1
            state["characters"] = int(state["characters"]) + characters
            state[status] = int(state[status]) + 1
            self.session_characters += characters
            self._write(state)

    def status(self) -> dict[str, object]:
        with self.lock:
            state = self._read()
            used = int(state["characters"])
            return {"requests": int(state["requests"]), "characters": used,
                    "successful": int(state["successful"]), "failed": int(state["failed"]),
                    "canceled": int(state["canceled"]), "warning": used >= self.limits.warning,
                    "monthlyCeiling": self.limits.monthly, "sessionCeiling": self.limits.session}

    def mark_canceled(self) -> None:
        with self.lock:
            state = self._read()
            if int(state["successful"]) > 0:
                state["successful"] = int(state["successful"]) - 1
                state["canceled"] = int(state["canceled"]) + 1
                self._write(state)


def default_ledger() -> UsageLedger:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MaeveV2"
    return UsageLedger(base / "elevenlabs-usage-counts.json")


def pcm_to_wav(pcm: bytes) -> bytes:
    if not pcm or len(pcm) % 2 or len(pcm) > MAX_AUDIO_BYTES:
        raise ProviderFailure("VOICE_AUDIO_FAILED")
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)
    value = stream.getvalue()
    validate_wav(value)
    return value


def validate_wav(value: bytes) -> dict[str, object]:
    if len(value) > MAX_AUDIO_BYTES or value[:4] != b"RIFF" or value[8:12] != b"WAVE":
        raise ProviderFailure("VOICE_AUDIO_FAILED")
    try:
        with wave.open(io.BytesIO(value), "rb") as handle:
            if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, SAMPLE_RATE):
                raise ProviderFailure("VOICE_AUDIO_FAILED")
            frames = handle.getnframes()
    except (wave.Error, EOFError):
        raise ProviderFailure("VOICE_AUDIO_FAILED") from None
    return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest(),
            "sampleRate": SAMPLE_RATE, "channels": 1, "frames": frames,
            "durationSeconds": frames / SAMPLE_RATE, "format": "RIFF/WAVE PCM-16"}


class ElevenLabsProvider:
    name = "ELEVENLABS"

    def __init__(self, ledger: UsageLedger | None = None, opener=None, credential_reader=credential_read) -> None:
        self.ledger = ledger or default_ledger()
        self.opener = opener or urllib.request.urlopen
        self.credential_reader = credential_reader
        self.lock = threading.Lock()
        self.active_response_id: str | None = None
        self.invalidated: set[str] = set()
        self.consumed: set[str] = set()
        self.audio: bytes | None = None
        self.audio_served = False
        self.connection = None

    def available(self) -> bool:
        secret = self.credential_reader()
        present = bool(secret)
        secret = None
        return present

    def status(self) -> dict[str, object]:
        available = self.available()
        return {"provider": "ELEVENLABS", "voice": ELEVENLABS_VOICE_NAME,
                "model": ELEVENLABS_MODEL, "available": available,
                "display": "CLOUD VOICE — ELEVENLABS" if available else "ELEVENLABS UNAVAILABLE — LOCAL FALLBACK REQUIRES APPROVAL",
                "usage": self.ledger.status()}

    def generate_response(self, text: str, response_id: str, *, timeout: float = 120) -> dict[str, object]:
        if not isinstance(response_id, str) or len(response_id) != 32:
            raise ProviderFailure("VOICE_IDENTITY_FAILED")
        if not 0.7 <= ELEVENLABS_SPEED <= 1.2:
            raise ProviderFailure("VOICE_CONFIGURATION_FAILED")
        text = text.strip()
        with self.lock:
            if response_id in self.consumed or response_id in self.invalidated or self.active_response_id is not None:
                raise ProviderFailure("VOICE_IDENTITY_FAILED")
            usage = self.ledger.authorize(len(text))
            key = self.credential_reader()
            if not key:
                raise ProviderFailure("VOICE_CREDENTIAL_MISSING")
            self.active_response_id = response_id
            self.consumed.add(response_id)
        body = json.dumps({"text": text, "model_id": ELEVENLABS_MODEL, "language_code": "en",
                           "voice_settings": {"speed": ELEVENLABS_SPEED}}, ensure_ascii=False).encode("utf-8")
        query = urllib.parse.urlencode({"output_format": ELEVENLABS_OUTPUT_FORMAT})
        request = urllib.request.Request(
            f"{ELEVENLABS_API}/text-to-speech/{urllib.parse.quote(ELEVENLABS_VOICE_ID)}/stream?{query}",
            data=body, method="POST",
            headers={"xi-api-key": key, "Accept": "application/octet-stream", "Content-Type": "application/json; charset=utf-8"},
        )
        key = None
        pcm = bytearray()
        status = "failed"
        try:
            response = self.opener(request, timeout=timeout)
            self.connection = response
            code = getattr(response, "status", 200)
            content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).split(";", 1)[0].lower()
            if code != 200 or content_type not in {"application/octet-stream", "audio/pcm", "audio/wav"}:
                raise ProviderFailure("VOICE_PROVIDER_RESPONSE_FAILED")
            while True:
                chunk = response.read(8192)
                if not chunk: break
                pcm.extend(chunk)
                if len(pcm) > MAX_AUDIO_BYTES: raise ProviderFailure("VOICE_AUDIO_FAILED")
            wav = pcm_to_wav(bytes(pcm))
            evidence = validate_wav(wav)
            with self.lock:
                if response_id in self.invalidated or self.active_response_id != response_id:
                    raise ProviderFailure("VOICE_IDENTITY_FAILED")
                self.audio, self.audio_served = wav, False
            status = "successful"
            return {"type": "generated", "status": "PASS", "text": text, "audio": evidence,
                    "provider": "ELEVENLABS", "voice": ELEVENLABS_VOICE_NAME,
                    "model": ELEVENLABS_MODEL, "usageWarning": usage["warning"]}
        except ProviderFailure:
            raise
        except (OSError, urllib.error.URLError):
            raise ProviderFailure("VOICE_PROVIDER_RESPONSE_FAILED") from None
        finally:
            try:
                if self.connection is not None: self.connection.close()
            except Exception:
                pass
            self.connection = None
            self.ledger.record(len(text), status)

    def take_audio(self, response_id: str) -> bytes:
        with self.lock:
            if response_id != self.active_response_id or response_id in self.invalidated or self.audio is None or self.audio_served:
                raise ProviderFailure("VOICE_IDENTITY_FAILED")
            self.audio_served = True
            return self.audio

    def complete(self, response_id: str) -> None:
        with self.lock:
            if response_id != self.active_response_id or self.audio is None or not self.audio_served:
                raise ProviderFailure("VOICE_IDENTITY_FAILED")
            self.audio = None; self.audio_served = False; self.active_response_id = None

    def cancel(self, response_id: str) -> str:
        with self.lock:
            if response_id in self.invalidated: return "ALREADY_CANCELLED"
            if self.active_response_id is None: return "NO_ACTIVE_RESPONSE"
            if response_id != self.active_response_id: raise ProviderFailure("VOICE_IDENTITY_FAILED")
            self.invalidated.add(response_id)
            connection = self.connection
            self.audio = None; self.audio_served = False; self.active_response_id = None
        try:
            if connection is not None: connection.close()
        except Exception:
            pass
        self.ledger.mark_canceled()
        return "CANCELLED"

    def stop(self) -> None:
        with self.lock:
            connection = self.connection
            self.connection = None; self.audio = None; self.audio_served = False; self.active_response_id = None
        try:
            if connection is not None: connection.close()
        except Exception:
            pass


class MockElevenLabsProvider(ElevenLabsProvider):
    """Non-network smoke provider with a fixed synthetic WAV."""

    def __init__(self, ledger: UsageLedger) -> None:
        super().__init__(ledger=ledger, credential_reader=lambda: "mock-nonsecret-credential-value")

    def generate_response(self, text: str, response_id: str, *, timeout: float = 120) -> dict[str, object]:
        if response_id in self.consumed or self.active_response_id is not None:
            raise ProviderFailure("VOICE_IDENTITY_FAILED")
        self.ledger.authorize(len(text))
        self.consumed.add(response_id); self.active_response_id = response_id
        self.audio = pcm_to_wav(b"\x00\x00" * 2400); self.audio_served = False
        self.ledger.record(len(text), "successful")
        return {"type":"generated","status":"PASS","text":text,"audio":validate_wav(self.audio),
                "provider":"ELEVENLABS","voice":ELEVENLABS_VOICE_NAME,"model":ELEVENLABS_MODEL,"usageWarning":False}
