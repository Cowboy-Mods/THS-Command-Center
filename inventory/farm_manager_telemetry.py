from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .maeve_telemetry import MaeveTelemetry


_STATE_MAP = {
    "IDLE": "idle",
    "RUNNING": "printing",
    "PRINTING": "printing",
    "PAUSE": "paused",
    "PAUSED": "paused",
    "FINISH": "finished",
    "FINISHED": "finished",
    "FAILED": "error",
    "ERROR": "error",
}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _camera_state(device: Mapping[str, Any], report: Mapping[str, Any]) -> tuple[bool, str]:
    stream = str(device.get("liveview_stream_status") or "").strip().casefold()
    camera = report.get("ip_cam") if isinstance(report.get("ip_cam"), Mapping) else {}
    present = str(camera.get("ipcam_dev") or "").strip().casefold()
    available = stream not in {"", "offline", "disabled", "unavailable"} or present not in {
        "", "0", "false", "offline", "disabled", "unavailable"
    }
    return available, "available" if available else "unavailable"


def _warning(report: Mapping[str, Any]) -> tuple[str | None, str | None]:
    hms = report.get("hms")
    if not isinstance(hms, list) or not hms:
        return None, None
    first = hms[0] if isinstance(hms[0], Mapping) else {}
    code = _text(first.get("code")) or _text(first.get("attr"))
    return code, "PRINTER WARNING REPORTED" if code or first else None


def _ams_inventory(report: Mapping[str, Any]) -> tuple[tuple[dict[str, Any], ...], int | None, int | None]:
    root = report.get("ams") if isinstance(report.get("ams"), Mapping) else {}
    units = root.get("ams") if isinstance(root.get("ams"), list) else []
    slots: list[dict[str, Any]] = []
    humidity: list[int | None] = []
    for unit_index, unit in enumerate(units[:8], start=1):
        if not isinstance(unit, Mapping):
            continue
        unit_number = (_integer(unit.get("id")) or 0) + 1
        humidity.append(_integer(unit.get("humidity")))
        trays = unit.get("tray") if isinstance(unit.get("tray"), list) else []
        for slot_index, tray in enumerate(trays[:4], start=1):
            if not isinstance(tray, Mapping):
                continue
            filament_type = _text(tray.get("tray_type"))
            raw_color = (_text(tray.get("tray_color")) or "").upper()
            color = f"#{raw_color[:6]}" if len(raw_color) >= 6 and all(c in "0123456789ABCDEF" for c in raw_color[:6]) else None
            remaining = _integer(tray.get("remain"))
            remaining = remaining if remaining is not None and 0 <= remaining <= 100 else None
            if filament_type or color:
                slots.append({
                    "unit": unit_number,
                    "slot": (_integer(tray.get("id")) or 0) + 1,
                    "filament_type": filament_type,
                    "filament_color": color,
                    "remaining_percent": remaining,
                })
    return tuple(slots), humidity[0] if humidity else None, humidity[1] if len(humidity) > 1 else None


def sanitize_farm_manager_devices(payload: Mapping[str, Any], *, observed_at: datetime | None = None) -> MaeveTelemetry:
    """Convert Farm Manager's devices2 response to Maeve's monitoring-only contract.

    The raw response must stay in memory. Identifiers, network addresses, tokens,
    account data, and unapproved fields are intentionally never copied.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("Farm Manager response must be an object")
    devices = payload.get("devices")
    if not isinstance(devices, list) or len(devices) != 1 or not isinstance(devices[0], Mapping):
        raise ValueError("exactly one Farm Manager printer is required")
    device = devices[0]
    report = device.get("report_status")
    if not isinstance(report, Mapping):
        raise ValueError("Farm Manager report status is missing")

    online = device.get("online") is True
    raw_state = str(report.get("gcode_state") or "").strip().upper()
    printer_state = _STATE_MAP.get(raw_state, "unknown") if online else "offline"
    if printer_state == "unknown" and _number(report.get("nozzle_target_temper")):
        printer_state = "heating"

    remaining_minutes = _integer(report.get("mc_remaining_time"))
    warning_code, warning_text = _warning(report)
    camera_available, camera_status = _camera_state(device, report)
    ams_slots, ams_1_humidity, ams_2_humidity = _ams_inventory(report)
    stamp = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)

    snapshot = MaeveTelemetry(
        source_provider="bambu_farm_manager",
        connection_state="online" if online else "offline",
        printer_state=printer_state,
        current_job_name=_text(report.get("subtask_name")) or _text(report.get("gcode_file")),
        progress_percent=_number(report.get("mc_percent")),
        remaining_seconds=max(0, remaining_minutes * 60) if remaining_minutes is not None else None,
        current_layer=_integer(report.get("layer_num")),
        total_layers=_integer(report.get("total_layer_num")),
        nozzle_actual_c=_number(report.get("nozzle_temper")),
        nozzle_target_c=_number(report.get("nozzle_target_temper")),
        bed_actual_c=_number(report.get("bed_temper")),
        bed_target_c=_number(report.get("bed_target_temper")),
        ams_slots=ams_slots,
        ams_1_humidity=ams_1_humidity,
        ams_2_humidity=ams_2_humidity,
        chamber_c=_number(report.get("chamber_temper")),
        warning_code=warning_code,
        warning_text=warning_text,
        camera_available=camera_available,
        camera_status=camera_status,
        last_source_update=stamp.isoformat().replace("+00:00", "Z"),
        source_health="farm_manager_live" if online else "farm_manager_offline",
        control_capable=False,
    )
    return snapshot.with_freshness(now=stamp)
