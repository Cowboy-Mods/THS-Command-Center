"""Offline portable-configuration QA; opens no service, WSL, microphone, or provider."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from runtime_config import ConfigurationError, load_config  # noqa: E402


def fixture() -> dict[str, object]:
    return {
        "voice": {"voice_id": "V" * 20},
        "windows": {"python_executable": "C:/portable/python.exe", "codex_executable": "C:/portable/codex.exe"},
        "runtime": {"root": str(ROOT)},
        "wsl": {
            "stt_distribution": "Maeve-STT", "stt_python": "/opt/stt/python",
            "stt_worker_path": "/mnt/c/portable/stt_worker.py", "stt_model_path": "/srv/models/stt",
            "qwen_distribution": None, "qwen_python": None, "qwen_worker_path": None,
            "qwen_model_path": None, "qwen_voice_identity_path": None
        },
        "microphone": {"approved_label": "Approved microphone", "approved_selector": "Approved microphone exact local selector"},
        "diagnostics": {"fixed_wav_path": None},
        "network": {"broker_host": "127.0.0.1", "broker_port": 48177, "reserved_test_port": 48178}
    }


def rejected(value: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        try: load_config(path, require_local_files=False)
        except ConfigurationError: return
        raise AssertionError("unsafe portable configuration was accepted")


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        good = fixture(); path.write_text(json.dumps(good), encoding="utf-8")
        loaded = load_config(path, require_local_files=False)
        assert loaded["host"] == "127.0.0.1" and loaded["broker_port"] == 48177
        assert loaded["qwen"]["distribution"] is None
    bad = fixture(); bad["network"]["broker_host"] = "0.0.0.0"; rejected(bad)
    for value in (None, "", "REQUIRED_LOCAL_VOICE_ID_NOT_CONFIGURED", "../invalid", 123, " V" * 10):
        bad = fixture(); bad["voice"]["voice_id"] = value; rejected(bad)
    bad = fixture(); del bad["voice"]; rejected(bad)
    bad = fixture(); bad["network"]["reserved_test_port"] = 48177; rejected(bad)
    bad = fixture(); bad["windows"]["api_key"] = "prohibited"; rejected(bad)
    bad = fixture(); bad["wsl"]["qwen_distribution"] = "Maeve-Qwen-TTS"; rejected(bad)
    bad = fixture(); bad["microphone"]["approved_selector"] = bad["microphone"]["approved_label"]; rejected(bad)
    print("PORTABLE_CONFIG_QA=PASS secret_fields=0 provider=0 wsl=0 microphone=0")


if __name__ == "__main__": main()
