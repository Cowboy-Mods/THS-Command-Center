from __future__ import annotations

import ipaddress
import json
import math
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from .credentials import load_p1s_access_code


class TelemetryConfigurationError(ValueError):
    """Read-only telemetry configuration is missing or unsafe."""


class TelemetryPayloadError(ValueError):
    """A device observation cannot be safely normalized."""


FEATURE_FLAG = "THS_P1S_TELEMETRY_ENABLED"
HOST_VARIABLE = "THS_P1S_HOST"
PORT_VARIABLE = "THS_P1S_MQTT_PORT"
SERIAL_VARIABLE = "THS_P1S_SERIAL"
ACCESS_CODE_VARIABLE = "THS_P1S_ACCESS_CODE"
STALE_AFTER_VARIABLE = "THS_P1S_STALE_AFTER_SECONDS"

SECRET_KEY_PARTS = ("access_code", "password", "token", "secret", "credential")
HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*$"
)


def _enabled(value: str | None) -> bool:
    normalized = (value or "").strip().casefold()
    if normalized in {"", "0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    raise TelemetryConfigurationError(
        f"{FEATURE_FLAG} must be true/false, yes/no, on/off, or 1/0"
    )


def telemetry_feature_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Return only the feature flag state; never inspect or expose credentials."""
    values = os.environ if environ is None else environ
    return _enabled(values.get(FEATURE_FLAG))


@dataclass(frozen=True)
class P1STelemetryConfig:
    enabled: bool
    host: str | None = None
    port: int = 8883
    serial: str | None = None
    access_code: str | None = field(default=None, repr=False)
    stale_after_seconds: int = 30
    equipment_number: str = "THS-EQP-000001"
    integration_type: str = "bambu_lan_mqtt_read_only"

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "P1STelemetryConfig":
        values = os.environ if environ is None else environ
        enabled = telemetry_feature_enabled(values)
        if not enabled:
            return cls(enabled=False)

        host = (values.get(HOST_VARIABLE) or "").strip()
        serial = (values.get(SERIAL_VARIABLE) or "").strip()
        access_code = (values.get(ACCESS_CODE_VARIABLE) or "").strip()
        if not host:
            raise TelemetryConfigurationError(f"{HOST_VARIABLE} is required when enabled")
        if not serial:
            raise TelemetryConfigurationError(f"{SERIAL_VARIABLE} is required when enabled")
        if not access_code:
            raise TelemetryConfigurationError(
                f"{ACCESS_CODE_VARIABLE} is required when enabled"
            )
        _validate_host(host)
        port = _bounded_int(values.get(PORT_VARIABLE, "8883"), PORT_VARIABLE, 1, 65535)
        stale_after = _bounded_int(
            values.get(STALE_AFTER_VARIABLE, "30"), STALE_AFTER_VARIABLE, 5, 3600
        )
        return cls(
            enabled=True,
            host=host,
            port=port,
            serial=serial,
            access_code=access_code,
            stale_after_seconds=stale_after,
        )

    @classmethod
    def from_protected_store(
        cls,
        environ: Mapping[str, str] | None = None,
        credential_path: Path | None = None,
    ) -> "P1STelemetryConfig":
        """Load non-secret settings normally and the access code from Windows DPAPI."""
        values = os.environ if environ is None else environ
        enabled = telemetry_feature_enabled(values)
        if not enabled:
            return cls(enabled=False)
        host = (values.get(HOST_VARIABLE) or "").strip()
        serial = (values.get(SERIAL_VARIABLE) or "").strip()
        if not host:
            raise TelemetryConfigurationError(f"{HOST_VARIABLE} is required when enabled")
        if not serial:
            raise TelemetryConfigurationError(f"{SERIAL_VARIABLE} is required when enabled")
        _validate_host(host)
        access_code = load_p1s_access_code(credential_path)
        port = _bounded_int(values.get(PORT_VARIABLE, "8883"), PORT_VARIABLE, 1, 65535)
        stale_after = _bounded_int(
            values.get(STALE_AFTER_VARIABLE, "30"), STALE_AFTER_VARIABLE, 5, 3600
        )
        return cls(
            enabled=True,
            host=host,
            port=port,
            serial=serial,
            access_code=access_code,
            stale_after_seconds=stale_after,
        )

    def safe_summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "serial_configured": bool(self.serial),
            "access_code_configured": bool(self.access_code),
            "stale_after_seconds": self.stale_after_seconds,
            "equipment_number": self.equipment_number,
            "integration_type": self.integration_type,
            "mode": "subscribe_only",
        }


def _validate_host(host: str) -> None:
    if "://" in host or "/" in host or "\\" in host or any(c.isspace() for c in host):
        raise TelemetryConfigurationError(f"{HOST_VARIABLE} must be one IP or hostname")
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    if not HOST_PATTERN.fullmatch(host):
        raise TelemetryConfigurationError(f"{HOST_VARIABLE} is not a valid IP or hostname")


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TelemetryConfigurationError(f"{name} must be a whole number") from exc
    if not minimum <= parsed <= maximum:
        raise TelemetryConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return parsed


@dataclass(frozen=True)
class PrinterTelemetry:
    equipment_number: str
    integration_type: str
    online_state: str
    printer_state: str | None
    active_job_name: str | None
    progress_percent: float | None
    remaining_seconds: int | None
    current_layer: int | None
    total_layers: int | None
    nozzle_temperature_c: float | None
    bed_temperature_c: float | None
    active_ams: int | None
    active_slot: int | None
    filament_type: str | None
    filament_color: str | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    source_device_time: str | None
    received_at: datetime
    last_successful_update_at: datetime | None
    stale: bool

    def as_dashboard_projection(self) -> dict[str, Any]:
        return {
            "equipment_number": self.equipment_number,
            "online_state": self.online_state,
            "printer_state": self.printer_state,
            "active_job_name": self.active_job_name,
            "progress_percent": self.progress_percent,
            "remaining_seconds": self.remaining_seconds,
            "current_layer": self.current_layer,
            "total_layers": self.total_layers,
            "nozzle_temperature_c": self.nozzle_temperature_c,
            "bed_temperature_c": self.bed_temperature_c,
            "active_ams": self.active_ams,
            "active_slot": self.active_slot,
            "filament_type": self.filament_type,
            "filament_color": self.filament_color,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "last_successful_update_at": _iso(self.last_successful_update_at),
            "stale": self.stale,
            "authority": "live_device_observation_only",
        }


class ReadOnlyPrinterAdapter(Protocol):
    """Subscribe-only adapter seam. It intentionally defines no command methods."""

    def observe(self) -> PrinterTelemetry:
        """Return one device observation without mutating any authoritative domain."""


@dataclass(frozen=True)
class BoundedReconnectPolicy:
    initial_seconds: float = 1.0
    maximum_seconds: float = 30.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.initial_seconds <= 0:
            raise ValueError("initial reconnect delay must be positive")
        if self.maximum_seconds < self.initial_seconds:
            raise ValueError("maximum reconnect delay must not be smaller than initial delay")
        if self.multiplier <= 1:
            raise ValueError("reconnect multiplier must be greater than one")

    def delay(self, failure_count: int) -> float:
        if failure_count < 1:
            return 0.0
        delay = self.initial_seconds
        for _ in range(failure_count - 1):
            delay *= self.multiplier
            if delay >= self.maximum_seconds:
                return self.maximum_seconds
        return delay


def parse_bambu_status(
    payload: Mapping[str, Any] | str,
    *,
    received_at: datetime | None = None,
    stale_after_seconds: int = 30,
) -> PrinterTelemetry:
    """Normalize a report payload; never treat observed AMS data as inventory truth."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TelemetryPayloadError("printer report is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise TelemetryPayloadError("printer report must be a JSON object")
    report = payload.get("print", payload)
    if not isinstance(report, Mapping):
        raise TelemetryPayloadError("printer report has no usable print object")

    received = _utc(received_at or datetime.now(timezone.utc))
    progress = _optional_float(report.get("mc_percent"), "progress", 0, 100)
    minutes = _optional_int(report.get("mc_remaining_time"), "remaining time", 0)
    current_layer = _optional_int(report.get("layer_num"), "current layer", 0)
    total_layers = _optional_int(report.get("total_layer_num"), "total layers", 0)
    nozzle = _optional_float(report.get("nozzle_temper"), "nozzle temperature", -50, 500)
    bed = _optional_float(report.get("bed_temper"), "bed temperature", -50, 200)
    active_ams, active_slot, filament_type, filament_color = _ams_values(report)
    errors = _messages(report.get("print_error"), ignore_zero=True)
    warnings = _hms_messages(report.get("hms"))
    source_time = _optional_text(report.get("device_time") or report.get("timestamp"))
    state = _optional_text(report.get("gcode_state") or report.get("print_status"))
    job = _optional_text(report.get("subtask_name") or report.get("gcode_file"))

    return PrinterTelemetry(
        equipment_number="THS-EQP-000001",
        integration_type="bambu_lan_mqtt_read_only",
        online_state="online",
        printer_state=state,
        active_job_name=job,
        progress_percent=progress,
        remaining_seconds=minutes * 60 if minutes is not None else None,
        current_layer=current_layer,
        total_layers=total_layers,
        nozzle_temperature_c=nozzle,
        bed_temperature_c=bed,
        active_ams=active_ams,
        active_slot=active_slot,
        filament_type=filament_type,
        filament_color=filament_color,
        errors=errors,
        warnings=warnings,
        source_device_time=source_time,
        received_at=received,
        last_successful_update_at=received,
        stale=stale_after_seconds <= 0,
    )


def disconnected_projection(
    previous: PrinterTelemetry | None,
    *,
    observed_at: datetime | None = None,
    stale_after_seconds: int = 30,
) -> PrinterTelemetry:
    now = _utc(observed_at or datetime.now(timezone.utc))
    if previous is None:
        return PrinterTelemetry(
            equipment_number="THS-EQP-000001",
            integration_type="bambu_lan_mqtt_read_only",
            online_state="unknown",
            printer_state=None,
            active_job_name=None,
            progress_percent=None,
            remaining_seconds=None,
            current_layer=None,
            total_layers=None,
            nozzle_temperature_c=None,
            bed_temperature_c=None,
            active_ams=None,
            active_slot=None,
            filament_type=None,
            filament_color=None,
            errors=(),
            warnings=(),
            source_device_time=None,
            received_at=now,
            last_successful_update_at=None,
            stale=True,
        )
    last = previous.last_successful_update_at
    stale = last is None or (now - _utc(last)).total_seconds() >= stale_after_seconds
    return replace(previous, online_state="offline", received_at=now, stale=stale)


def sanitize_for_log(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    """Return a log-safe copy without credential-like keys or supplied secret values."""
    secret_values = tuple(item for item in secrets if item)
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.casefold().replace("-", "_")
            if any(part in normalized for part in SECRET_KEY_PARTS):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = sanitize_for_log(item, secrets=secret_values)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_for_log(item, secrets=secret_values) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secret_values:
            result = result.replace(secret, "[REDACTED]")
        return result
    return value


def _ams_values(report: Mapping[str, Any]) -> tuple[int | None, int | None, str | None, str | None]:
    ams = report.get("ams")
    if not isinstance(ams, Mapping):
        return None, None, None, None
    tray_now = _optional_int(ams.get("tray_now"), "active AMS tray", 0)
    if tray_now is None or tray_now > 15:
        return None, None, None, None
    ams_index, slot_index = divmod(tray_now, 4)
    filament_type = filament_color = None
    units = ams.get("ams")
    if isinstance(units, list):
        unit = next(
            (item for item in units if isinstance(item, Mapping) and str(item.get("id")) == str(ams_index)),
            None,
        )
        trays = unit.get("tray") if isinstance(unit, Mapping) else None
        if isinstance(trays, list):
            tray = next(
                (item for item in trays if isinstance(item, Mapping) and str(item.get("id")) == str(slot_index)),
                None,
            )
            if isinstance(tray, Mapping):
                filament_type = _optional_text(tray.get("tray_type"))
                filament_color = _optional_text(tray.get("tray_color"))
    return ams_index + 1, slot_index + 1, filament_type, filament_color


def _messages(value: Any, *, ignore_zero: bool = False) -> tuple[str, ...]:
    if value in (None, "", [], {}):
        return ()
    if ignore_zero and str(value).strip() in {"0", "0.0"}:
        return ()
    if isinstance(value, list):
        return tuple(filter(None, (_optional_text(item) for item in value)))
    text = _optional_text(value)
    return (text,) if text else ()


def _hms_messages(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return _messages(value)
    messages = []
    for item in value:
        if isinstance(item, Mapping):
            text = _optional_text(item.get("msg") or item.get("code") or item.get("attr"))
        else:
            text = _optional_text(item)
        if text:
            messages.append(text)
    return tuple(messages)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any, label: str, minimum: int) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise TelemetryPayloadError(f"{label} must be a number")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TelemetryPayloadError(f"{label} must be a number") from exc
    if parsed < minimum:
        raise TelemetryPayloadError(f"{label} is outside the accepted range")
    return parsed


def _optional_float(
    value: Any, label: str, minimum: float, maximum: float
) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise TelemetryPayloadError(f"{label} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TelemetryPayloadError(f"{label} must be a number") from exc
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise TelemetryPayloadError(f"{label} is outside the accepted range")
    return parsed


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None
