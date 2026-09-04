"""Fail-closed portable configuration for the Maeve headset voice runtime."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


CONFIG_ENV = "MAEVE_CONFIG_PATH"
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.local.json"
LOOPBACK_HOST = "127.0.0.1"
SECRET_FIELD = re.compile(r"(?:api.?key|password|secret|token|cookie|authorization|credential)", re.I)
WSL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def valid_voice_id(value: Any) -> bool:
    """Validate local resource syntax without disclosing or contacting it."""
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9]{20}", value) is not None


class ConfigurationError(RuntimeError):
    """A content-free startup error safe to show to an operator."""


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration section is missing or invalid: {name}")
    return value


def _text(section: dict[str, Any], key: str, *, optional: bool = False) -> str | None:
    value = section.get(key)
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ConfigurationError(f"Configuration field is missing or invalid: {key}")
    return value.strip()


def _port(section: dict[str, Any], key: str) -> int:
    value = section.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 1024 <= value <= 65535:
        raise ConfigurationError(f"Configuration port is invalid: {key}")
    return value


def _posix_path(section: dict[str, Any], key: str, *, optional: bool = False) -> str | None:
    value = _text(section, key, optional=optional)
    if value is None:
        return None
    if not value.startswith("/") or "\\" in value or "/../" in f"/{value.strip('/')}/":
        raise ConfigurationError(f"WSL path is not absolute and normalized: {key}")
    return value


def _windows_path(section: dict[str, Any], key: str, *, required_file: bool) -> str:
    value = _text(section, key)
    assert value is not None
    path = Path(value)
    if not path.is_absolute():
        raise ConfigurationError(f"Windows path is not absolute: {key}")
    if required_file and not path.is_file():
        raise ConfigurationError(f"Required local executable is unavailable: {key}")
    return str(path)


def load_config(path: Path | None = None, *, require_local_files: bool = True) -> dict[str, Any]:
    config_path = (path or Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG))).resolve()
    if not config_path.is_file():
        raise ConfigurationError("Local Maeve configuration is missing; copy config.example.json to config.local.json")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError("Local Maeve configuration is unreadable or malformed") from error
    root = _object(raw, "root")
    if any(SECRET_FIELD.search(str(key)) for section in root.values() if isinstance(section, dict) for key in section):
        raise ConfigurationError("Secret-shaped configuration fields are prohibited")
    if set(root) != {"windows", "runtime", "wsl", "microphone", "diagnostics", "network", "voice"}:
        raise ConfigurationError("Configuration contains missing or unknown top-level sections")

    windows = _object(root["windows"], "windows")
    runtime = _object(root["runtime"], "runtime")
    wsl = _object(root["wsl"], "wsl")
    microphone = _object(root["microphone"], "microphone")
    diagnostics = _object(root["diagnostics"], "diagnostics")
    network = _object(root["network"], "network")
    voice = _object(root["voice"], "voice")
    if set(voice) != {"voice_id"} or not valid_voice_id(voice.get("voice_id")):
        raise ConfigurationError("Required local voice configuration is missing or invalid")
    runtime_root = Path(_text(runtime, "root") or "")
    if not runtime_root.is_absolute() or runtime_root.resolve() != Path(__file__).resolve().parent:
        raise ConfigurationError("Configured runtime root does not identify this release copy")
    host = _text(network, "broker_host")
    if host != LOOPBACK_HOST:
        raise ConfigurationError("Maeve broker host must be exact IPv4 loopback")
    broker_port = _port(network, "broker_port")
    reserved_port = _port(network, "reserved_test_port")
    if broker_port == reserved_port:
        raise ConfigurationError("Broker and reserved ports must differ")
    stt_distribution = _text(wsl, "stt_distribution") or ""
    if not WSL_NAME.fullmatch(stt_distribution):
        raise ConfigurationError("STT distribution name is invalid")
    qwen_distribution = _text(wsl, "qwen_distribution", optional=True)
    if qwen_distribution is not None and not WSL_NAME.fullmatch(qwen_distribution):
        raise ConfigurationError("Qwen distribution name is invalid")
    qwen_fields = {
        "distribution": qwen_distribution,
        "python": _posix_path(wsl, "qwen_python", optional=True),
        "worker_path": _posix_path(wsl, "qwen_worker_path", optional=True),
        "model_path": _posix_path(wsl, "qwen_model_path", optional=True),
        "voice_identity_path": _posix_path(wsl, "qwen_voice_identity_path", optional=True),
    }
    if any(value is not None for value in qwen_fields.values()) and not all(value is not None for value in qwen_fields.values()):
        raise ConfigurationError("Optional Qwen configuration must be entirely present or entirely absent")
    diagnostic = _text(diagnostics, "fixed_wav_path", optional=True)
    if diagnostic is not None and not Path(diagnostic).is_absolute():
        raise ConfigurationError("Optional diagnostic WAV path must be absolute")
    approved_label = _text(microphone, "approved_label") or ""
    approved_selector = _text(microphone, "approved_selector") or ""
    if approved_label == approved_selector or len(approved_selector) < len(approved_label):
        raise ConfigurationError("Approved microphone selector must be more specific than its public label")

    return {
        "config_path": str(config_path),
        "voice_id": voice["voice_id"],
        "python_executable": _windows_path(windows, "python_executable", required_file=require_local_files),
        "codex_executable": _windows_path(windows, "codex_executable", required_file=require_local_files),
        "runtime_root": str(runtime_root.resolve()),
        "stt_distribution": stt_distribution,
        "stt_python": _posix_path(wsl, "stt_python"),
        "stt_worker_path": _posix_path(wsl, "stt_worker_path"),
        "stt_model_path": _posix_path(wsl, "stt_model_path"),
        "qwen": qwen_fields,
        "approved_label": approved_label,
        "approved_selector": approved_selector,
        "diagnostic_wav": diagnostic,
        "host": host,
        "broker_port": broker_port,
        "reserved_port": reserved_port,
    }


def export_environment(config: dict[str, Any]) -> dict[str, str]:
    values = {
        CONFIG_ENV: str(config["config_path"]),
        "MAEVE_CODEX_EXECUTABLE": str(config["codex_executable"]),
        "MAEVE_STT_MODEL_PATH": str(config["stt_model_path"]),
    }
    qwen = config["qwen"]
    if qwen["model_path"] is not None:
        values["MAEVE_QWEN_MODEL_PATH"] = str(qwen["model_path"])
        values["MAEVE_QWEN_IDENTITY_PATH"] = str(qwen["voice_identity_path"])
    return values
