from __future__ import annotations

import json
import sys
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from inventory.credentials import CredentialStoreError, load_p1s_access_code
from inventory.maeve_local_config import load_printer_host
from inventory.maeve_telemetry import (
    AtomicTelemetryStore,
    iso,
    sanitize_telemetry_payload,
    utc_now,
    write_rainmeter_feed,
)
from inventory.p1s_mqtt import SubscribeOnlyConnectionError, capture_one_report
from inventory.telemetry import P1STelemetryConfig, TelemetryPayloadError, parse_bambu_status


PRIVATE_CONFIG = Path(r"C:\THS\OctoEverywhere\data\octoeverywhere.conf")
STATE_PATH = Path.home() / "Documents" / "THS-Command-Center-Data" / "runtime" / "maeve-telemetry.json"
RAINMETER_FEED = (
    Path.home()
    / "Documents"
    / "Rainmeter"
    / "Skins"
    / "THS"
    / "CommandCenter"
    / "Bambu"
    / "BambuStatus.txt"
)


def _private_serial() -> str:
    try:
        lines = PRIVATE_CONFIG.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("private serial configuration is unavailable") from exc
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key.strip().casefold() == "printer_serial_number":
            serial = value.strip()
            if serial:
                return serial
    raise ValueError("private serial configuration is incomplete")


def _printer_state(value: str | None) -> str:
    normalized = (value or "unknown").strip().casefold()
    aliases = {
        "idle": "idle",
        "finish": "finished",
        "finished": "finished",
        "running": "printing",
        "printing": "printing",
        "prepare": "heating",
        "slicing": "heating",
        "pause": "paused",
        "paused": "paused",
        "failed": "error",
        "error": "error",
        "offline": "offline",
    }
    return aliases.get(normalized, "unknown")


def _warning_summary(errors: tuple[str, ...], warnings: tuple[str, ...]) -> tuple[str | None, str | None]:
    if errors:
        return "PRINTER_ERROR", "; ".join(errors)[:240]
    if warnings:
        return "PRINTER_WARNING", "; ".join(warnings)[:240]
    return None, None


def _result(stage: str, status: str, **details: object) -> None:
    print(json.dumps({"stage": stage, "status": status, **details}, sort_keys=True))


def main() -> int:
    diagnostics: dict[str, object] = {
        "connection_attempts": 0,
        "mqtt_publishes_sent": 0,
        "printer_control_operations": 0,
    }
    try:
        serial = _private_serial()
        access_code = load_p1s_access_code()
        if not access_code.strip():
            raise CredentialStoreError("protected credential is empty")
    except (CredentialStoreError, ValueError):
        _result("credential_gate", "failed", category="protected_configuration_unavailable")
        return 3

    config = P1STelemetryConfig(
        enabled=True,
        host=load_printer_host(),
        port=8883,
        serial=serial,
        access_code=access_code,
        stale_after_seconds=45,
    )
    try:
        diagnostics["connection_attempts"] = 1
        raw_payload = capture_one_report(
            config,
            timeout_seconds=30.0,
            diagnostics=diagnostics,
        )
        observed = parse_bambu_status(raw_payload, stale_after_seconds=45)
    except SubscribeOnlyConnectionError as exc:
        failure = exc.safe_summary()
        stage = str(failure.pop("stage"))
        _result(stage, "failed", **diagnostics, **failure)
        return 2
    except TelemetryPayloadError:
        _result("payload_validation", "failed", category="invalid_status_report")
        return 2
    finally:
        access_code = ""
        serial = ""

    warning_code, warning_text = _warning_summary(observed.errors, observed.warnings)
    now = utc_now()
    snapshot = sanitize_telemetry_payload(
        {
            "connection_state": "online",
            "printer_state": _printer_state(observed.printer_state),
            "current_job_name": observed.active_job_name,
            "progress_percent": observed.progress_percent,
            "remaining_seconds": observed.remaining_seconds,
            "current_layer": observed.current_layer,
            "total_layers": observed.total_layers,
            "nozzle_actual_c": observed.nozzle_temperature_c,
            "bed_actual_c": observed.bed_temperature_c,
            "active_ams_unit": observed.active_ams + 1 if observed.active_ams is not None else None,
            "active_ams_slot": observed.active_slot + 1 if observed.active_slot is not None else None,
            "filament_type": observed.filament_type,
            "filament_color": observed.filament_color,
            "warning_code": warning_code,
            "warning_text": warning_text,
            "camera_available": None,
            "camera_status": "not_reported",
            "last_source_update": iso(now),
        }
    ).with_freshness(now, stale_after_seconds=45)
    AtomicTelemetryStore(STATE_PATH).write(snapshot)
    write_rainmeter_feed(RAINMETER_FEED, snapshot)
    populated = sorted(
        key
        for key, value in snapshot.as_dict().items()
        if key in {
            "connection_state", "printer_state", "current_job_name", "progress_percent",
            "remaining_seconds", "current_layer", "total_layers", "nozzle_actual_c",
            "bed_actual_c", "active_ams_unit", "active_ams_slot", "filament_type",
            "filament_color", "warning_code", "warning_text", "camera_available",
            "camera_status",
        }
        and value is not None
    )
    _result(
        "sanitized_persistence",
        "succeeded",
        **diagnostics,
        authentication=True,
        subscription=True,
        telemetry_received=True,
        display_mode=snapshot.display_mode,
        printer_state=snapshot.printer_state,
        populated_fields=populated,
        control_capable=snapshot.control_capable,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
