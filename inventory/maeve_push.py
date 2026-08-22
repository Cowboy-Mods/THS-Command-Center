from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .credentials import _protect, _restrict_windows_acl, _unprotect


class PushConfigurationError(RuntimeError):
    pass


class ProtectedWebPushService:
    """DPAPI-protected Web Push config; sends generic read-only alerts only."""

    def __init__(self, runtime_dir: Path):
        self.root = Path(runtime_dir) / "push"
        self.private_key_path = self.root / "vapid-private.dpapi"
        self.subscription_path = self.root / "subscription.dpapi"
        self.sent_path = self.root / "sent-alerts.json"
        self._lock = threading.Lock()

    def public_key(self) -> str:
        from cryptography.hazmat.primitives import serialization
        raw = self._load_or_create_private_key().public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def save_subscription(self, value: dict[str, object]) -> None:
        endpoint, keys = value.get("endpoint"), value.get("keys")
        if not isinstance(endpoint, str) or urlsplit(endpoint).scheme != "https" or len(endpoint) > 2048:
            raise PushConfigurationError("invalid push endpoint")
        if not isinstance(keys, dict):
            raise PushConfigurationError("missing push keys")
        normalized: dict[str, object] = {"endpoint": endpoint, "keys": {}}
        for name in ("p256dh", "auth"):
            item = keys.get(name)
            if not isinstance(item, str) or not 16 <= len(item) <= 256 or not _is_base64url(item):
                raise PushConfigurationError("invalid push key")
            normalized["keys"][name] = item
        self._store_protected(self.subscription_path, json.dumps(normalized, separators=(",", ":")).encode())

    def status(self) -> dict[str, bool]:
        return {"configured": self.subscription_path.is_file(), "background_capable": True}

    def send_pending(self, alerts: list[dict[str, str]]) -> int:
        if not self.subscription_path.is_file():
            return 0
        with self._lock:
            sent = self._load_sent()
            pending = [item for item in reversed(alerts) if item.get("id") and item["id"] not in sent]
            for alert in pending:
                self._send(alert)
                sent.append(alert["id"])
            self._save_sent(sent[-100:])
            return len(pending)

    def _send(self, alert: dict[str, str]) -> None:
        from cryptography.hazmat.primitives import serialization
        from pywebpush import webpush
        subscription = json.loads(_unprotect(self.subscription_path.read_bytes()).decode())
        private_key = self._load_or_create_private_key().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode("ascii")
        # Deliberately excludes job names, telemetry details, printer identity, and credentials.
        permitted = {
            "complete": ("PRINT COMPLETE", "Maeve reports that the active print has finished."),
            "paused": ("PRINT PAUSED", "Maeve reports that the printer is paused."),
            "error": ("PRINTER ATTENTION", "Maeve reports that the printer needs attention."),
            "warning": ("PRINTER WARNING", "Maeve reports a printer warning."),
            "stale": ("TELEMETRY STALE", "Maeve is no longer receiving fresh printer data."),
            "offline": ("PRINTER DISCONNECTED", "Maeve reports that the printer feed is offline."),
            "recovered": ("PRINTER RECONNECTED", "Maeve reports that the printer feed is live again."),
            "first-layer-complete": ("FIRST LAYER COMPLETE", "The printer has advanced beyond layer one."),
            "milestone-25": ("PRINT 25%", "The active print has reached twenty-five percent."),
            "milestone-50": ("PRINT 50%", "The active print has reached fifty percent."),
            "milestone-75": ("PRINT 75%", "The active print has reached seventy-five percent."),
        }
        title, body = permitted.get(alert.get("kind", ""), ("MAEVE ALERT", "Maeve has a printer status update."))
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body, "kind": alert.get("kind", "notice")}, separators=(",", ":")),
            vapid_private_key=private_key,
            vapid_claims={"sub": "mailto:maeve@localhost"}, ttl=3600, timeout=10,
        )

    def _load_or_create_private_key(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        if self.private_key_path.is_file():
            return serialization.load_pem_private_key(_unprotect(self.private_key_path.read_bytes()), password=None)
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self._store_protected(self.private_key_path, pem)
        return key

    def _store_protected(self, path: Path, value: bytes) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(_protect(value)); os.chmod(temporary, 0o600)
        os.replace(temporary, path); os.chmod(path, 0o600); _restrict_windows_acl(path)

    def _load_sent(self) -> list[str]:
        try:
            value = json.loads(self.sent_path.read_text(encoding="utf-8"))
            return [item for item in value if isinstance(item, str)][-100:] if isinstance(value, list) else []
        except (OSError, ValueError):
            return []

    def _save_sent(self, value: list[str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.sent_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, self.sent_path); _restrict_windows_acl(self.sent_path)


def _is_base64url(value: str) -> bool:
    return all(character.isalnum() or character in "-_=" for character in value)
