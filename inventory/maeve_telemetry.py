from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol


SCHEMA_VERSION = "1.0"
ALLOWED_CONNECTION_STATES = {"online", "offline", "unknown"}
ALLOWED_PRINTER_STATES = {
    "offline", "idle", "heating", "printing", "paused", "finished", "error", "unknown"
}
ALLOWED_MODES = {"LIVE", "STALE", "OFFLINE", "DEMO"}
ALLOWED_CAMERA_STATES = {"available", "unavailable", "offline", "unknown", "not_reported"}
SECRET_PARTS = ("access", "password", "token", "secret", "credential", "serial", "email", "ip")
CONTROL_CAPABILITY = False
INGESTIBLE_FIELDS = frozenset({
    "connection_state",
    "printer_state",
    "current_job_name",
    "progress_percent",
    "remaining_seconds",
    "current_layer",
    "total_layers",
    "nozzle_actual_c",
    "nozzle_target_c",
    "bed_actual_c",
    "bed_target_c",
    "active_ams_unit",
    "active_ams_slot",
    "ams_slots",
    "filament_type",
    "filament_color",
    "warning_code",
    "warning_text",
    "camera_available",
    "camera_status",
    "last_source_update",
})


def default_state_path() -> Path:
    configured = os.environ.get("THS_MAEVE_TELEMETRY_STATE")
    if configured:
        return Path(configured)
    return Path.home() / "Documents" / "THS-Command-Center-Data" / "runtime" / "maeve-telemetry.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass(frozen=True)
class MaeveTelemetry:
    schema_version: str = SCHEMA_VERSION
    source_provider: str = "offline"
    printer_model: str = "Bambu Lab P1S"
    display_name: str = "THS Printer"
    connection_state: str = "offline"
    printer_state: str = "offline"
    current_job_name: str | None = None
    current_plate_name: str | None = None
    progress_percent: float | None = None
    remaining_seconds: int | None = None
    remaining_formatted: str = "N/A"
    current_layer: int | None = None
    total_layers: int | None = None
    nozzle_actual_c: float | None = None
    nozzle_target_c: float | None = None
    bed_actual_c: float | None = None
    bed_target_c: float | None = None
    chamber_c: float | None = None
    active_ams_unit: int | None = None
    active_ams_slot: int | None = None
    ams_slots: tuple[dict[str, Any], ...] = ()
    filament_type: str | None = None
    filament_color: str | None = None
    camera_available: bool | None = None
    camera_status: str = "not_reported"
    ams_1_humidity: int | None = None
    ams_2_humidity: int | None = None
    warning_code: str | None = None
    warning_text: str | None = None
    last_source_update: str | None = None
    last_gateway_update: str | None = None
    data_age_seconds: int | None = None
    stale: bool = True
    offline: bool = True
    display_mode: str = "OFFLINE"
    control_capable: bool = CONTROL_CAPABILITY
    source_health: str = "not_configured"
    provenance: str = "THS sanitized local telemetry contract"
    demo_label: str | None = None

    def validate(self) -> "MaeveTelemetry":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported telemetry schema version")
        if self.connection_state not in ALLOWED_CONNECTION_STATES:
            raise ValueError("invalid connection state")
        if self.printer_state not in ALLOWED_PRINTER_STATES:
            raise ValueError("invalid printer state")
        if self.display_mode not in ALLOWED_MODES:
            raise ValueError("invalid display mode")
        if self.control_capable is not False:
            raise ValueError("THS-facing telemetry must never be control capable")
        if self.camera_available is not None and not isinstance(self.camera_available, bool):
            raise ValueError("camera availability must be true, false, or null")
        if self.camera_status not in ALLOWED_CAMERA_STATES:
            raise ValueError("invalid camera status")
        if self.display_mode == "DEMO" and not self.demo_label:
            raise ValueError("demo telemetry must be visibly labeled")
        if self.display_mode != "DEMO" and self.demo_label:
            raise ValueError("fixture labels are valid only in demo mode")
        _bounded(self.progress_percent, 0, 100, "progress")
        for name, value in (("remaining", self.remaining_seconds), ("current layer", self.current_layer),
                            ("total layers", self.total_layers), ("data age", self.data_age_seconds)):
            _bounded(value, 0, None, name)
        for name, value, high in (
            ("nozzle actual", self.nozzle_actual_c, 500), ("nozzle target", self.nozzle_target_c, 500),
            ("bed actual", self.bed_actual_c, 200), ("bed target", self.bed_target_c, 200),
            ("chamber", self.chamber_c, 120),
        ):
            _bounded(value, -50, high, name)
        for name, value in (("AMS unit", self.active_ams_unit), ("AMS slot", self.active_ams_slot)):
            _bounded(value, 1, 8 if name == "AMS unit" else 4, name)
        if len(self.ams_slots) > 32:
            raise ValueError("too many AMS slots")
        for slot in self.ams_slots:
            if not isinstance(slot, Mapping) or set(slot) != {"unit", "slot", "filament_type", "filament_color", "remaining_percent"}:
                raise ValueError("invalid AMS slot record")
            _bounded(slot["unit"], 1, 8, "AMS unit")
            _bounded(slot["slot"], 1, 4, "AMS slot")
            if slot["filament_type"] is not None and not isinstance(slot["filament_type"], str):
                raise ValueError("invalid AMS filament type")
            if slot["filament_color"] is not None and not re.fullmatch(r"#[0-9A-F]{6}", slot["filament_color"]):
                raise ValueError("invalid AMS filament color")
            _bounded(slot["remaining_percent"], 0, 100, "AMS remaining")
        for name, value in (("AMS 1 humidity", self.ams_1_humidity), ("AMS 2 humidity", self.ams_2_humidity)):
            _bounded(value, 0, 100, name)
        forbidden = _find_secret_fields(asdict(self))
        if forbidden:
            raise ValueError(f"secret-bearing telemetry fields are prohibited: {', '.join(forbidden)}")
        return self

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def with_freshness(self, now: datetime | None = None, stale_after_seconds: int = 45) -> "MaeveTelemetry":
        now = now or utc_now()
        source = parse_time(self.last_source_update)
        age = max(0, int((now - source).total_seconds())) if source else None
        stale = self.connection_state != "online" or age is None or age >= stale_after_seconds
        mode = self.display_mode
        if mode != "DEMO":
            mode = "OFFLINE" if self.connection_state != "online" else ("STALE" if stale else "LIVE")
        return replace(
            self,
            remaining_formatted=format_duration(self.remaining_seconds),
            last_gateway_update=iso(now),
            data_age_seconds=age,
            stale=stale,
            offline=self.connection_state != "online",
            display_mode=mode,
        ).validate()


class TelemetryProvider(Protocol):
    def observe(self) -> MaeveTelemetry:
        """Return sanitized status. The provider interface intentionally has no commands."""


class OfflineProvider:
    def observe(self) -> MaeveTelemetry:
        return MaeveTelemetry().with_freshness()


class FixtureProvider:
    def __init__(self, fixture_path: Path, fixture_name: str):
        self.fixture_path = Path(fixture_path)
        self.fixture_name = fixture_name

    def observe(self) -> MaeveTelemetry:
        fixtures = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        if self.fixture_name not in fixtures:
            raise ValueError(f"unknown fixture: {self.fixture_name}")
        values = dict(fixtures[self.fixture_name])
        now = utc_now()
        values.update(
            source_provider="fixture",
            display_mode="DEMO",
            demo_label=f"DEMO / {self.fixture_name.upper().replace('_', ' ')} / TEST DATA",
            last_source_update=iso(now),
            control_capable=False,
        )
        return MaeveTelemetry(**values).with_freshness(now)


class OctoEverywhereProvider(Protocol):
    """Future adapter seam; no API is invented before a supported local source exists."""

    def observe(self) -> MaeveTelemetry:
        ...


def sanitize_telemetry_payload(payload: Mapping[str, Any]) -> MaeveTelemetry:
    """Accept only the THS monitoring allowlist; reject secrets, controls, and raw payloads."""
    if not isinstance(payload, Mapping):
        raise ValueError("telemetry payload must be an object")
    keys = {str(key) for key in payload}
    secret_keys = sorted(
        key for key in keys if any(part in key.casefold() for part in SECRET_PARTS)
    )
    if secret_keys:
        raise ValueError("secret-bearing telemetry fields are prohibited")
    unapproved = sorted(keys - INGESTIBLE_FIELDS)
    if unapproved:
        raise ValueError("unapproved telemetry fields are prohibited")
    values = {key: payload[key] for key in INGESTIBLE_FIELDS if key in payload}
    return MaeveTelemetry(**values, control_capable=False).validate()


class AtomicTelemetryStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def write(self, snapshot: MaeveTelemetry) -> None:
        payload = json.dumps(snapshot.as_dict(), indent=2, sort_keys=True) + "\n"
        _atomic_write(self.path, payload)

    def read(self) -> MaeveTelemetry:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return MaeveTelemetry(**raw).validate()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return OfflineProvider().observe()


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "N/A"
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def rainmeter_line(snapshot: MaeveTelemetry) -> str:
    value = snapshot.validate()
    mode_text = (
        "OFFLINE / CONNECTION NOT CONFIGURED"
        if value.display_mode == "OFFLINE" and value.source_health == "not_configured"
        else value.display_mode
    )
    fields = [
        mode_text,
        value.connection_state.upper(),
        value.printer_state.upper(),
        value.current_job_name or "NOT REPORTED",
        f"{value.progress_percent:.0f}" if value.progress_percent is not None else "0",
        value.remaining_formatted,
        _pair(value.current_layer, value.total_layers),
        _temp_pair(value.nozzle_actual_c, value.nozzle_target_c),
        _temp_pair(value.bed_actual_c, value.bed_target_c),
        _ams(value.active_ams_unit, value.active_ams_slot),
        " / ".join(filter(None, (value.filament_type, value.filament_color))) or "NOT REPORTED",
        value.warning_text or value.warning_code or "NONE",
        value.last_gateway_update or "NO UPDATE",
        value.demo_label or "SANITIZED LOCAL CONTRACT / NO CONTROL",
    ]
    return "|".join(_clean(item) for item in fields) + "\n"


def write_rainmeter_feed(path: Path, snapshot: MaeveTelemetry) -> None:
    _atomic_write(Path(path), rainmeter_line(snapshot))


def compare_reported_slot(
    snapshot: MaeveTelemetry,
    verified_spool_id: str | None = None,
    *,
    maintenance_restricted: bool = False,
) -> dict[str, Any]:
    return {
        "ams_unit": snapshot.active_ams_unit,
        "slot": snapshot.active_ams_slot,
        "reported_material": snapshot.filament_type,
        "reported_color": snapshot.filament_color,
        "verified_spool_id": verified_spool_id,
        "match_confidence": "verified" if verified_spool_id else "unmatched",
        "mismatch_warning": None if verified_spool_id else "UNMATCHED",
        "maintenance_restriction": bool(maintenance_restricted),
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            if os.name != "nt":
                os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _find_secret_fields(value: Mapping[str, Any]) -> list[str]:
    return [key for key in value if any(part in key.casefold() for part in SECRET_PARTS)]


def _bounded(value: float | int | None, low: float, high: float | None, name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or value < low or (high is not None and value > high):
        raise ValueError(f"{name} is outside the accepted range")


def _clean(value: Any) -> str:
    return re.sub(r"[|\r\n]+", " ", str(value)).strip()


def _pair(current: int | None, total: int | None) -> str:
    return f"{current if current is not None else 'N/A'} / {total if total is not None else 'N/A'}"


def _temp_pair(actual: float | None, target: float | None) -> str:
    def show(item: float | None) -> str:
        return "N/A" if item is None else f"{item:.0f} C"
    return f"{show(actual)} / {show(target)}"


def _ams(unit: int | None, slot: int | None) -> str:
    return f"AMS {unit} / SLOT {slot}" if unit and slot else "NOT REPORTED"
