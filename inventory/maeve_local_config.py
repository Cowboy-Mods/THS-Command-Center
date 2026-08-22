from __future__ import annotations

import ipaddress
import json
from pathlib import Path


LOCAL_CONFIG_PATH = (
    Path.home()
    / "Documents"
    / "THS-Command-Center-Data"
    / "runtime"
    / "maeve-local-config.json"
)


class MaeveLocalConfigError(ValueError):
    pass


def load_printer_host(path: Path = LOCAL_CONFIG_PATH) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_host = payload["printer_host"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise MaeveLocalConfigError("local printer configuration is unavailable") from exc
    if not isinstance(raw_host, str) or raw_host != raw_host.strip():
        raise MaeveLocalConfigError("local printer host must be a clean IP address")
    try:
        host = ipaddress.ip_address(raw_host)
    except ValueError as exc:
        raise MaeveLocalConfigError("local printer host is invalid") from exc
    if not (host.is_private or host.is_loopback):
        raise MaeveLocalConfigError("local printer host must not be public")
    return str(host)
