from __future__ import annotations

import json
import secrets
import ssl
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import paho.mqtt.client as mqtt

from inventory.credentials import CredentialStoreError, load_p1s_access_code
from inventory.maeve_local_config import load_printer_host
from inventory.maeve_telemetry import (
    AtomicTelemetryStore,
    iso,
    sanitize_telemetry_payload,
    utc_now,
    write_rainmeter_feed,
)
from inventory.telemetry import TelemetryPayloadError, parse_bambu_status


PRIVATE_CONFIG = Path(r"C:\THS\OctoEverywhere\data\octoeverywhere.conf")
STATE_PATH = Path.home() / "Documents" / "THS-Command-Center-Data" / "runtime" / "maeve-telemetry.json"
DIAGNOSTIC_PATH = (
    Path.home()
    / "Documents"
    / "THS-Command-Center-Data"
    / "runtime"
    / "maeve-paho-diagnostic.json"
)
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


@dataclass
class PacketCounts:
    connect: int = 0
    subscribe: int = 0
    outgoing_publish: int = 0
    other: dict[str, int] = field(default_factory=dict)

    def record(self, command: int) -> None:
        packet_type = (int(command) >> 4) & 0x0F
        if packet_type == 1:
            self.connect += 1
        elif packet_type == 8:
            self.subscribe += 1
        elif packet_type == 3:
            self.outgoing_publish += 1
        else:
            name = str(packet_type)
            self.other[name] = self.other.get(name, 0) + 1

    def safe_summary(self) -> dict[str, Any]:
        return {
            "connect": self.connect,
            "subscribe": self.subscribe,
            "publish": self.outgoing_publish,
            "other_packet_types": dict(sorted(self.other.items())),
        }


class _CountingClient(mqtt.Client):
    def __init__(self, *args: Any, packet_counts: PacketCounts, **kwargs: Any):
        self._packet_counts = packet_counts
        super().__init__(*args, **kwargs)

    def _packet_queue(
        self,
        command: int,
        packet: bytes,
        mid: int,
        qos: int,
        info: mqtt.MQTTMessageInfo | None = None,
    ) -> mqtt.MQTTErrorCode:
        self._packet_counts.record(command)
        return super()._packet_queue(command, packet, mid, qos, info)


def _printer_state(value: str | None) -> str:
    normalized = (value or "unknown").strip().casefold()
    return {
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
    }.get(normalized, "unknown")


def _warning_summary(errors: tuple[str, ...], warnings: tuple[str, ...]) -> tuple[str | None, str | None]:
    if errors:
        return "PRINTER_ERROR", "; ".join(errors)[:240]
    if warnings:
        return "PRINTER_WARNING", "; ".join(warnings)[:240]
    return None, None


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


class SubscribeOnlyPahoDiagnostic:
    """One connection, one exact subscription, one report, and no command surface."""

    def run(self) -> tuple[int, dict[str, Any]]:
        result: dict[str, Any] = {
            "provider": "eclipse-paho",
            "paho_version": "2.1.0",
            "connection_attempts": 0,
            "tcp_result": "not_attempted",
            "tls_result": "not_attempted",
            "tls_version": None,
            "tls_cipher": None,
            "on_connect_reason": None,
            "on_subscribe_received": False,
            "on_subscribe_reason": None,
            "on_disconnect_reason": None,
            "telemetry_received": False,
            "callback_sequence": [],
            "packet_counts": {},
            "printer_control_operations": 0,
            "rainmeter_refreshed": False,
            "status": "failed",
            "failure_stage": "credential_gate",
            "failure_category": "protected_configuration_unavailable",
        }
        try:
            serial = _private_serial()
            access_code = load_p1s_access_code()
            if not access_code.strip():
                raise CredentialStoreError("protected credential is empty")
        except (CredentialStoreError, ValueError):
            _atomic_json(DIAGNOSTIC_PATH, result)
            return 3, result

        topic = f"device/{serial}/report"
        packet_counts = PacketCounts()
        client_id = "MaevePaho" + secrets.token_hex(5)
        client = _CountingClient(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
            protocol=mqtt.MQTTv311,
            transport="tcp",
            reconnect_on_failure=False,
            packet_counts=packet_counts,
        )
        client._connect_timeout = 5.0
        client.username_pw_set("bblp", access_code)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        client.tls_set_context(context)

        raw_payload: str | None = None
        connected_at: float | None = None
        finished = False

        def on_connect(
            active: mqtt.Client,
            userdata: Any,
            flags: mqtt.ConnectFlags,
            reason_code: mqtt.ReasonCode,
            properties: mqtt.Properties | None,
        ) -> None:
            nonlocal connected_at, finished
            result["callback_sequence"].append("on_connect")
            result["on_connect_reason"] = int(reason_code.value)
            if reason_code.is_failure:
                result["failure_stage"] = "connack"
                result["failure_category"] = "authentication_rejected"
                finished = True
                return
            connected_at = time.monotonic()
            result["failure_stage"] = "suback_wait"
            result["failure_category"] = "subscription_not_confirmed"
            sock = active.socket()
            if isinstance(sock, ssl.SSLSocket):
                result["tcp_result"] = "accepted"
                result["tls_result"] = "established"
                result["tls_version"] = sock.version()
                cipher = sock.cipher()
                result["tls_cipher"] = cipher[0] if cipher else None
            rc, _ = active.subscribe(topic, qos=0)
            if rc != mqtt.MQTT_ERR_SUCCESS:
                result["failure_stage"] = "subscribe_queue"
                result["failure_category"] = "subscribe_not_queued"
                finished = True

        def on_subscribe(
            active: mqtt.Client,
            userdata: Any,
            mid: int,
            reason_codes: list[mqtt.ReasonCode],
            properties: mqtt.Properties | None,
        ) -> None:
            nonlocal finished
            result["callback_sequence"].append("on_subscribe")
            result["on_subscribe_received"] = True
            granted = int(reason_codes[0].value) if reason_codes else None
            result["on_subscribe_reason"] = granted
            if reason_codes and reason_codes[0].is_failure:
                result["failure_stage"] = "suback"
                result["failure_category"] = "subscription_rejected"
                finished = True
            else:
                result["failure_stage"] = "telemetry_wait"
                result["failure_category"] = "telemetry_timeout"

        def on_message(active: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
            nonlocal raw_payload, finished
            if message.topic != topic:
                return
            try:
                raw_payload = message.payload.decode("utf-8")
            except UnicodeDecodeError:
                result["failure_stage"] = "payload_validation"
                result["failure_category"] = "non_utf8_report"
                finished = True
                return
            result["callback_sequence"].append("on_message")
            result["telemetry_received"] = True
            finished = True

        def on_disconnect(
            active: mqtt.Client,
            userdata: Any,
            disconnect_flags: mqtt.DisconnectFlags,
            reason_code: mqtt.ReasonCode,
            properties: mqtt.Properties | None,
        ) -> None:
            nonlocal finished
            result["callback_sequence"].append("on_disconnect")
            result["on_disconnect_reason"] = int(reason_code.value)
            if not result["telemetry_received"]:
                finished = True

        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        try:
            result["connection_attempts"] = 1
            result["failure_stage"] = "tcp_tls_connect"
            result["failure_category"] = "connection_failed"
            client.connect(load_printer_host(), port=8883, keepalive=15)
            absolute_deadline = time.monotonic() + 30.0
            while not finished and time.monotonic() < absolute_deadline:
                if connected_at is not None and time.monotonic() - connected_at >= 20.0:
                    result["failure_stage"] = (
                        "telemetry_wait" if result["on_subscribe_received"] else "suback_wait"
                    )
                    result["failure_category"] = "timeout"
                    break
                rc = client.loop(timeout=0.25)
                if rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
                    break
        except (OSError, ssl.SSLError):
            pass
        finally:
            try:
                client.disconnect()
                client.loop(timeout=0.1)
            except (OSError, ssl.SSLError):
                pass
            access_code = ""
            serial = ""

        result["packet_counts"] = packet_counts.safe_summary()
        if packet_counts.connect != 1 or packet_counts.subscribe > 1 or packet_counts.outgoing_publish != 0:
            result["failure_stage"] = "packet_safety"
            result["failure_category"] = "outgoing_packet_invariant_failed"
            _atomic_json(DIAGNOSTIC_PATH, result)
            return 4, result

        if raw_payload is None:
            _atomic_json(DIAGNOSTIC_PATH, result)
            return 2, result
        try:
            observed = parse_bambu_status(raw_payload, stale_after_seconds=45)
        except TelemetryPayloadError:
            result["failure_stage"] = "payload_validation"
            result["failure_category"] = "invalid_status_report"
            _atomic_json(DIAGNOSTIC_PATH, result)
            return 2, result

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
        result.update(
            status="succeeded",
            failure_stage=None,
            failure_category=None,
            display_mode=snapshot.display_mode,
            printer_state=snapshot.printer_state,
            control_capable=snapshot.control_capable,
        )
        _atomic_json(DIAGNOSTIC_PATH, result)
        return 0, result


def main() -> int:
    code, result = SubscribeOnlyPahoDiagnostic().run()
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
