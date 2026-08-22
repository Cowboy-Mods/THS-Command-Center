from __future__ import annotations

import html
import ipaddress
import json
import mimetypes
import os
import secrets
import subprocess
import threading
from datetime import datetime, timezone
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .maeve_telemetry import AtomicTelemetryStore
from .queries import DatabaseNotReady, InventoryQueries


@dataclass(frozen=True)
class ConsolePaths:
    telemetry_state: Path
    camera_result: Path
    camera_frame: Path
    maeve_art: Path
    database: Path
    print_library: Path
    bambu_studio: Path
    dashboard_launcher: Path
    documentation: Path


class LocalActionLauncher:
    def __init__(self, camera_adapter=None, process_factory=subprocess.Popen):
        self.camera_adapter = camera_adapter
        self.process_factory = process_factory

    def open(self, name: str, target: Path) -> bool:
        if not target.exists():
            return False
        if name == "bambu-studio":
            if self.camera_adapter is None or not self.camera_adapter.release_for_bambu_studio():
                return False
            process = self.process_factory([str(target)], cwd=str(target.parent))
            threading.Thread(target=self._wait_for_studio, args=(process,), daemon=True).start()
            return True
        os.startfile(str(target))
        return True

    def _wait_for_studio(self, process) -> None:
        process.wait()
        self.camera_adapter.mark_bambu_studio_exited()


class ReadOnlyAlertTracker:
    """Detect sanitized state transitions without exposing a control path."""

    def __init__(self, maximum: int = 20):
        self.maximum = maximum
        self._previous: tuple[str, str, str | None, str | None] | None = None
        self._alerts: list[dict[str, str]] = []
        self._previous_progress: float | None = None
        self._previous_layer: int | None = None
        self._lock = threading.Lock()

    def observe(self, telemetry) -> list[dict[str, str]]:
        current = (telemetry.display_mode, telemetry.printer_state, telemetry.warning_code, telemetry.warning_text)
        with self._lock:
            previous = self._previous
            prior_progress = self._previous_progress
            prior_layer = self._previous_layer
            self._previous = current
            current_progress = telemetry.progress_percent if telemetry.printer_state == "printing" else None
            current_layer = telemetry.current_layer if telemetry.printer_state == "printing" else None
            self._previous_progress = current_progress
            self._previous_layer = current_layer
            if previous is not None:
                prior_mode, prior_state, prior_warning, _ = previous
                mode, state, warning, warning_text = current
                if prior_state in {"printing", "paused"} and state in {"finished", "idle"}:
                    self._add("complete", "PRINT COMPLETE", "The active print has finished.")
                if prior_state != "paused" and state == "paused":
                    self._add("paused", "PRINT PAUSED", "The printer reports a paused job.")
                if prior_state != "error" and state == "error":
                    self._add("error", "PRINTER ATTENTION", warning_text or "The printer reports an error.")
                if not prior_warning and warning:
                    self._add("warning", "PRINTER WARNING", warning_text or "A sanitized printer warning was reported.")
                if prior_mode == "LIVE" and mode == "STALE":
                    self._add("stale", "TELEMETRY STALE", "Maeve is no longer receiving fresh printer data.")
                if prior_mode in {"LIVE", "STALE"} and mode == "OFFLINE":
                    self._add("offline", "PRINTER DISCONNECTED", "The sanitized printer feed is offline.")
                if prior_mode in {"STALE", "OFFLINE"} and mode == "LIVE":
                    self._add("recovered", "PRINTER RECONNECTED", "The sanitized printer feed is live again.")
                if prior_state == "printing" and state == "printing" and prior_progress is not None and current_progress is not None and current_progress >= prior_progress:
                    for threshold in (25, 50, 75):
                        if prior_progress < threshold <= current_progress:
                            self._add(f"milestone-{threshold}", f"PRINT {threshold}%", f"The active print has reached {threshold} percent.")
                if prior_state == "printing" and state == "printing" and prior_layer is not None and current_layer is not None and prior_layer <= 1 < current_layer:
                    self._add("first-layer-complete", "FIRST LAYER COMPLETE", "The printer has advanced beyond layer one.")
            return [dict(item) for item in self._alerts]

    def _add(self, kind: str, title: str, message: str) -> None:
        self._alerts.insert(0, {
            "id": f"{datetime.now(timezone.utc).timestamp():.6f}-{kind}",
            "kind": kind,
            "title": title,
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        del self._alerts[self.maximum:]


class MaeveConsoleApp:
    def __init__(self, paths: ConsolePaths, camera_adapter, launcher: LocalActionLauncher | None = None, alert_tracker: ReadOnlyAlertTracker | None = None, push_service=None):
        self.paths = paths
        self.camera_adapter = camera_adapter
        self.launcher = launcher or LocalActionLauncher(camera_adapter)
        self.alert_tracker = alert_tracker or ReadOnlyAlertTracker()
        self.push_service = push_service
        self._csrf_token = secrets.token_urlsafe(32)

    def response(self, target: str, *, method: str = "GET", request_headers=None, request_body: bytes = b"") -> tuple[int, list[tuple[str, str]], bytes]:
        request_headers = request_headers or {}
        if method not in {"GET", "HEAD", "POST"}:
            return self._text(405, "Method not allowed")
        parsed = urlsplit(target)
        path = parsed.path
        if path == "/":
            return self._html(200, self._page())
        if path == "/api/status":
            if method == "POST":
                return self._text(405, "Method not allowed")
            return self._json(200, self.status())
        if path == "/api/push-public-key":
            if method == "POST" or self.push_service is None:
                return self._json(503, {"background_capable": False})
            return self._json(200, {"background_capable": True, "public_key": self.push_service.public_key()})
        if path == "/api/push-subscription":
            if method != "POST" or self.push_service is None:
                return self._text(405 if method != "POST" else 503, "Background alerts unavailable")
            if request_headers.get("X-Maeve-CSRF") != self._csrf_token or not self._same_origin(request_headers):
                return self._text(403, "Protected registration rejected")
            try:
                self.push_service.save_subscription(json.loads(request_body.decode("utf-8")))
            except (ValueError, UnicodeDecodeError, RuntimeError):
                return self._text(400, "Invalid subscription")
            return self._json(200, {"configured": True, "monitoring_only": True})
        if method == "POST":
            return self._text(405, "Method not allowed")
        if path == "/manifest.webmanifest":
            return self._manifest()
        if path == "/service-worker.js":
            return self._service_worker()
        if path == "/assets/maeve-app-icon.svg":
            return self._app_icon()
        if path == "/api/camera":
            viewer = parse_qs(parsed.query).get("viewer", [""])[-1]
            return self._json(200, self.camera_adapter.touch_viewer(viewer))
        if path == "/camera/frame.jpg":
            viewer = parse_qs(parsed.query).get("viewer", [""])[-1]
            camera = self.camera_adapter.touch_viewer(viewer)
            if not camera["available"] or not self.paths.camera_frame.is_file():
                return self._text(404, "Camera frame unavailable")
            body = self.paths.camera_frame.read_bytes()
            self.camera_adapter.mark_frame_delivered(int(camera.get("frame_version", 0)))
            headers = self._headers("image/jpeg", len(body))
            headers.append(("X-Maeve-Camera-State", str(camera["state"])))
            return 200, headers, body
        if path == "/assets/maeve.webp":
            if not self.paths.maeve_art.is_file():
                return self._text(404, "Maeve artwork unavailable")
            content_type = mimetypes.guess_type(self.paths.maeve_art.name)[0] or "image/webp"
            return 200, self._headers(content_type, self.paths.maeve_art.stat().st_size), self.paths.maeve_art.read_bytes()
        if path == "/docs":
            return self._html(200, self._documentation_page())
        if path == "/inventory/filament":
            return self._html(200, self._filament_inventory_page(parse_qs(parsed.query)))
        if path == "/print-library":
            return self._html(200, self._print_library_page(parse_qs(parsed.query)))
        if path == "/dashboard" or path.startswith("/dashboard/"):
            return self._dashboard_response(parsed, method)
        if path.startswith("/launch/"):
            name = path.removeprefix("/launch/")
            targets = {
                "bambu-studio": self.paths.bambu_studio,
                "print-library": self.paths.print_library,
                "dashboard": self.paths.dashboard_launcher,
                "documentation": self.paths.documentation,
            }
            selected = targets.get(name)
            if selected is None:
                return self._text(404, "Unknown local action")
            opened = self.launcher.open(name, selected)
            return self._json(200 if opened else 409, {"opened": opened, "local_only": True})
        return self._text(404, "Not found")

    def status(self) -> dict[str, object]:
        telemetry = AtomicTelemetryStore(self.paths.telemetry_state).read().with_freshness(stale_after_seconds=90)
        camera = self.camera_adapter.status()
        alerts = self.alert_tracker.observe(telemetry)
        loaded_slots = " / ".join(
            f"{chr(64 + int(slot['unit']))}{slot['slot']} {slot['filament_type'] or 'UNKNOWN'} {slot['filament_color'] or ''}"
            + (f" {slot['remaining_percent']}%" if slot['remaining_percent'] is not None else " REMAINING UNKNOWN")
            for slot in telemetry.ams_slots
        ) or "NONE REPORTED"
        return {
            "service_state": "LOCAL / READY",
            "printer_connection": telemetry.connection_state.upper(),
            "camera_adapter": f"CAMERA {camera['state']}",
            "camera_available": camera["available"],
            "camera_last_update": camera.get("last_frame"),
            "telemetry_state": f"{telemetry.display_mode} / FARM MANAGER",
            "printer_state": telemetry.printer_state.upper(),
            "current_job": telemetry.current_job_name or "NO ACTIVE JOB",
            "progress": f"{telemetry.progress_percent:.0f}%" if telemetry.progress_percent is not None else "NOT REPORTED",
            "progress_percent": telemetry.progress_percent,
            "remaining_time": telemetry.remaining_formatted,
            "layer": f"{telemetry.current_layer or 0} / {telemetry.total_layers or 0}",
            "temperatures": f"NOZZLE {telemetry.nozzle_actual_c or 0:.0f} C / BED {telemetry.bed_actual_c or 0:.0f} C",
            "ams_slot": (
                f"AMS {telemetry.active_ams_unit} / SLOT {telemetry.active_ams_slot}"
                if telemetry.active_ams_unit and telemetry.active_ams_slot else "NOT REPORTED BY FARM MANAGER"
            ),
            "ams_loaded": loaded_slots,
            "ams_slots": [dict(slot) for slot in telemetry.ams_slots],
            "data_age_seconds": telemetry.data_age_seconds,
            "last_source_update": telemetry.last_source_update,
            "alerts": alerts,
            "alerts_read_only": True,
            "background_alerts": self.push_service.status() if self.push_service is not None else {"configured": False, "background_capable": False},
            "filament_inventory": "AVAILABLE / READ-ONLY" if self.paths.database.is_file() else "UNAVAILABLE",
            "print_library": "AVAILABLE" if self.paths.print_library.is_dir() else "UNAVAILABLE",
            "sanitized_state": telemetry.display_mode,
            "control_capable": False,
            "remote_access": False,
        }

    def _page(self) -> str:
        values = self.status()
        esc = html.escape
        camera = '<img id="camera-frame" class="camera-frame" alt="Local P1S camera frame"><div id="camera-offline" class="offline-box">CAMERA OFFLINE</div><p class="fine">LAST FRAME: <span id="camera-time">NOT REPORTED</span> &mdash; AGE: <span id="camera-age">NOT REPORTED</span></p><button id="refresh-camera" class="camera-refresh" type="button">REFRESH CAMERA</button>'
        return self._shell(
            "Maeve Command Console",
            f"""
            <header class="hero"><div class="portrait" role="img" aria-label="Maeve"></div><div>
              <p class="eyebrow">THS / TOP HAT SYNDICATE</p><h1>MAEVE COMMAND CONSOLE</h1>
              <p class="ready">MAEVE READY</p><p>Local command partner. Monitoring-only foundation.</p>
            </div></header>
            <main class="grid">
              <section class="panel printer-panel"><div class="live-head"><h2>PRINTER</h2><div><span id="live-badge" class="status-badge {esc(str(values['sanitized_state']).lower())}">{esc(str(values['sanitized_state']))}</span><span id="telemetry-age" class="telemetry-age">UPDATED {esc(str(values['data_age_seconds'] if values['data_age_seconds'] is not None else 'N/A'))}S AGO</span></div></div>
              <div class="job-name" id="current-job">{esc(str(values['current_job']))}</div>
              <div class="metric-grid"><article class="metric"><span>PROGRESS</span><strong id="progress-value">{esc(str(values['progress']))}</strong></article><article class="metric"><span>REMAINING</span><strong id="remaining-value">{esc(str(values['remaining_time']))}</strong></article><article class="metric"><span>LAYER</span><strong id="layer">{esc(str(values['layer']))}</strong></article><article class="metric"><span>TEMPERATURES</span><strong id="temperatures">{esc(str(values['temperatures']))}</strong></article></div>
              <div class="progress-track" aria-label="Print progress"><div id="progress-fill" class="progress-fill" style="width:{float(values['progress_percent'] or 0):.0f}%"></div></div><dl class="printer-details">
                <div><dt>P1S connection</dt><dd id="printer-connection">{esc(str(values['printer_connection']))}</dd></div>
                <div><dt>Camera</dt><dd id="camera-state">{esc(str(values['camera_adapter']))}</dd></div>
                <div><dt>Telemetry</dt><dd id="telemetry-state">{esc(str(values['telemetry_state']))}</dd></div>
                <div><dt>Active AMS</dt><dd id="ams-slot">{esc(str(values['ams_slot']))}</dd></div>
              </dl><h3>ALERTS</h3><div class="alert-toolbar"><button id="enable-alerts" class="camera-refresh" type="button">ENABLE ALERTS WHILE OPEN</button><button id="enable-background-alerts" class="camera-refresh" type="button">ENABLE BACKGROUND ALERTS</button><span id="alert-permission" class="fine">IN-CONSOLE ALERTS ACTIVE</span></div><div id="alert-list" class="alert-list"><p class="fine">NO NEW ALERTS</p></div><h3>AMS INVENTORY</h3><div id="ams-swatches" class="ams-grid"></div><p id="ams-loaded" class="fine">{esc(str(values['ams_loaded']))}</p>{camera}</section>
              <section class="panel"><h2>THS INVENTORY</h2><dl>
                <div><dt>Filament inventory</dt><dd>{esc(str(values['filament_inventory']))}</dd></div>
                <div><dt>Print library</dt><dd>{esc(str(values['print_library']))}</dd></div>
                <div><dt>Inventory mutation</dt><dd>DISABLED</dd></div>
              </dl><div class="actions"><a href="/inventory/filament">VIEW FILAMENT INVENTORY</a>
              <a href="/print-library">VIEW THS PRINT LIBRARY</a></div></section>
              <section class="panel"><h2>QUICK ACTIONS</h2><div class="actions">
                <a href="/inventory/filament">FILAMENT INVENTORY</a>
                <a href="/print-library">THS PRINT LIBRARY</a>
                <a href="/launch/bambu-studio">DESKTOP: OPEN BAMBU STUDIO</a>
                <a href="/dashboard/">VIEW THS DASHBOARD</a>
                <a href="/docs">OPEN MAEVE STATUS</a>
              </div><p class="fine">Inventory and Print Library stay in this browser. DESKTOP actions open only on Cowboy's PC. No print or printer-control action exists here.</p></section>
              <section class="panel"><h2>SYSTEM</h2><dl>
                <div><dt>Maeve service</dt><dd>LOCAL / READY</dd></div>
                <div><dt>Camera adapter</dt><dd id="system-camera-state">{esc(str(values['camera_adapter']))}</dd></div>
                <div><dt>Telemetry source</dt><dd>FARM MANAGER / READ ONLY</dd></div>
                <div><dt>Sanitized state</dt><dd id="sanitized-state">{esc(str(values['sanitized_state']))}</dd></div>
                <div><dt>Printer control</dt><dd>DISABLED</dd></div>
                <div><dt>Remote access</dt><dd>NOT EXPOSED</dd></div>
              </dl></section>
            </main><script>
            (() => {{
              const viewer = crypto.randomUUID().replaceAll('-', '_');
              const state = document.getElementById('camera-state');
              const systemState = document.getElementById('system-camera-state');
              const frame = document.getElementById('camera-frame');
              const offline = document.getElementById('camera-offline');
              const stamp = document.getElementById('camera-time');
              const age = document.getElementById('camera-age');
              const refresh = document.getElementById('refresh-camera');
              const telemetryFields = {{
                printer_connection: document.getElementById('printer-connection'),
                telemetry_state: document.getElementById('telemetry-state'),
                ams_slot: document.getElementById('ams-slot'),
                ams_loaded: document.getElementById('ams-loaded'),
                sanitized_state: document.getElementById('sanitized-state')
              }};
              const liveBadge = document.getElementById('live-badge');
              const telemetryAge = document.getElementById('telemetry-age');
              const progressValue = document.getElementById('progress-value');
              const remainingValue = document.getElementById('remaining-value');
              const progressFill = document.getElementById('progress-fill');
              const job = document.getElementById('current-job');
              const layer = document.getElementById('layer');
              const temperatures = document.getElementById('temperatures');
              const amsSwatches = document.getElementById('ams-swatches');
              const alertList = document.getElementById('alert-list');
              const enableAlerts = document.getElementById('enable-alerts');
              const enableBackgroundAlerts = document.getElementById('enable-background-alerts');
              const alertPermission = document.getElementById('alert-permission');
              let newestAlert = null;
              let sequence = 0;
              let lastFrameTime = null;
              let deliveredLive = false;
              function updateAge() {{
                age.textContent = lastFrameTime ? Math.max(0, Math.floor((Date.now() - lastFrameTime) / 1000)) + ' SECONDS' : 'NOT REPORTED';
              }}
              function updateStatus(camera) {{
                const normalFrameHandoff = deliveredLive && camera.state === 'CONNECTING' && camera.available;
                if (!normalFrameHandoff) {{
                  state.textContent = 'CAMERA ' + camera.state;
                  systemState.textContent = 'CAMERA ' + camera.state;
                }}
                if (camera.state === 'LIVE') deliveredLive = true;
                if (['STALE', 'OFFLINE', 'RELEASED FOR BAMBU STUDIO'].includes(camera.state)) deliveredLive = false;
                lastFrameTime = camera.last_frame ? Date.parse(camera.last_frame) : null;
                stamp.textContent = lastFrameTime ? new Date(lastFrameTime).toLocaleTimeString() : 'NOT REPORTED';
                updateAge();
              }}
              async function pollTelemetry() {{
                try {{
                  const response = await fetch('/api/status', {{cache:'no-store'}});
                  const current = await response.json();
                  for (const [key, element] of Object.entries(telemetryFields)) element.textContent = current[key];
                  job.textContent = current.current_job;
                  layer.textContent = current.layer;
                  temperatures.textContent = current.temperatures;
                  progressValue.textContent = current.progress;
                  remainingValue.textContent = current.remaining_time;
                  const percent = Number.isFinite(current.progress_percent) ? Math.max(0, Math.min(100, current.progress_percent)) : 0;
                  progressFill.style.width = percent + '%';
                  liveBadge.textContent = current.sanitized_state;
                  liveBadge.className = 'status-badge ' + String(current.sanitized_state).toLowerCase();
                  telemetryAge.textContent = current.data_age_seconds == null ? 'UPDATE AGE NOT REPORTED' : 'UPDATED ' + current.data_age_seconds + 'S AGO';
                  amsSwatches.replaceChildren();
                  for (const slot of current.ams_slots || []) {{
                    const chip = document.createElement('article'); chip.className = 'ams-chip';
                    const dot = document.createElement('span'); dot.className = 'color-dot';
                    if (/^#[0-9A-F]{{6}}$/.test(slot.filament_color || '')) dot.style.backgroundColor = slot.filament_color;
                    const name = document.createElement('strong'); name.textContent = String.fromCharCode(64 + Number(slot.unit)) + slot.slot;
                    const material = document.createElement('span'); material.textContent = slot.filament_type || 'EMPTY';
                    const remaining = document.createElement('small'); remaining.textContent = slot.remaining_percent == null ? 'REMAINING UNKNOWN' : slot.remaining_percent + '% REMAINING';
                    chip.append(dot, name, material, remaining); amsSwatches.append(chip);
                  }}
                  alertList.replaceChildren();
                  if (!(current.alerts || []).length) {{ const empty = document.createElement('p'); empty.className = 'fine'; empty.textContent = 'NO NEW ALERTS'; alertList.append(empty); }}
                  for (const alert of current.alerts || []) {{
                    const item = document.createElement('article'); item.className = 'alert-item ' + alert.kind;
                    const resolved = current.sanitized_state === 'LIVE' && ['offline', 'stale'].includes(alert.kind);
                    const title = document.createElement('strong'); title.textContent = resolved ? 'RESOLVED — ' + alert.title : alert.title;
                    const message = document.createElement('span'); message.textContent = resolved ? 'The printer feed is live again. This earlier alert is retained for history.' : alert.message;
                    const when = document.createElement('small'); when.textContent = new Date(alert.created_at).toLocaleTimeString();
                    item.append(title, message, when); alertList.append(item);
                  }}
                  const latest = (current.alerts || [])[0];
                  if (latest && latest.id !== newestAlert) {{
                    if (newestAlert && 'Notification' in window && Notification.permission === 'granted') new Notification(latest.title, {{body:latest.message, tag:latest.kind}});
                    newestAlert = latest.id;
                  }}
                }} catch (_) {{}}
              }}
              enableAlerts.addEventListener('click', async () => {{
                if (!('Notification' in window)) {{ alertPermission.textContent = 'SYSTEM NOTIFICATIONS NOT SUPPORTED HERE'; return; }}
                const result = await Notification.requestPermission();
                alertPermission.textContent = result === 'granted' ? 'ALERTS ENABLED WHILE THIS PAGE IS OPEN' : 'SYSTEM ALERTS NOT ENABLED';
              }});
              function decodeApplicationKey(value) {{
                const padding = '='.repeat((4 - value.length % 4) % 4);
                const raw = atob((value + padding).replaceAll('-', '+').replaceAll('_', '/'));
                return Uint8Array.from(raw, character => character.charCodeAt(0));
              }}
              enableBackgroundAlerts.addEventListener('click', async () => {{
                try {{
                  if (!('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error();
                  if (Notification.permission !== 'granted' && await Notification.requestPermission() !== 'granted') throw new Error();
                  const key = await (await fetch('/api/push-public-key', {{cache:'no-store'}})).json();
                  if (!key.background_capable || !key.public_key) throw new Error();
                  const registration = await navigator.serviceWorker.ready;
                  let subscription = await registration.pushManager.getSubscription();
                  if (!subscription) subscription = await registration.pushManager.subscribe({{userVisibleOnly:true, applicationServerKey:decodeApplicationKey(key.public_key)}});
                  const saved = await fetch('/api/push-subscription', {{method:'POST', headers:{{'Content-Type':'application/json','X-Maeve-CSRF':'{self._csrf_token}'}}, body:JSON.stringify(subscription)}});
                  if (!saved.ok) throw new Error();
                  alertPermission.textContent = 'BACKGROUND ALERTS ENABLED';
                }} catch (_) {{ alertPermission.textContent = 'BACKGROUND ALERTS NOT ENABLED'; }}
              }});
              async function poll(force = false) {{
                if (document.hidden && !force) return;
                try {{
                  const response = await fetch('/api/camera?viewer=' + encodeURIComponent(viewer), {{cache:'no-store'}});
                  const camera = await response.json();
                  updateStatus(camera);
                  if (camera.available) {{
                    frame.style.display = 'block'; offline.style.display = 'none';
                    frame.src = '/camera/frame.jpg?viewer=' + encodeURIComponent(viewer) + '&v=' + (++sequence) + '-' + Date.now();
                  }} else {{ frame.style.display = 'none'; offline.style.display = 'block'; }}
                }} catch (_) {{ state.textContent = 'CAMERA OFFLINE'; systemState.textContent = 'CAMERA OFFLINE'; }}
              }}
              frame.addEventListener('load', async () => {{
                try {{
                  const response = await fetch('/api/camera?viewer=' + encodeURIComponent(viewer), {{cache:'no-store'}});
                  updateStatus(await response.json());
                }} catch (_) {{}}
              }});
              frame.addEventListener('error', () => {{
                deliveredLive = false;
                state.textContent = 'CAMERA CONNECTING';
                systemState.textContent = 'CAMERA CONNECTING';
              }});
              document.addEventListener('visibilitychange', () => {{ if (!document.hidden) poll(); }});
              refresh.addEventListener('click', () => poll(true));
              setInterval(updateAge, 1000);
              if ('serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js', {{scope:'/'}}).catch(() => {{}});
              poll(); pollTelemetry();
              setInterval(poll, 2000); setInterval(pollTelemetry, 2000);
            }})();
            </script>""",
        )

    def _dashboard_response(self, parsed, method: str):
        if method not in {"GET", "HEAD"}:
            return self._text(405, "Phone dashboard is read-only")
        relative = parsed.path.removeprefix("/dashboard") or "/"
        if relative == "/read-only":
            return self._html(200, self._dashboard_read_only_page())
        if relative != "/":
            return self._text(403, "This dashboard route is not available in read-only phone mode")
        return self._html(200, self._phone_dashboard_page())

    def _phone_dashboard_page(self) -> str:
        try:
            totals = InventoryQueries(self.paths.database).dashboard()
        except DatabaseNotReady:
            return self._shell(
                "THS Dashboard",
                """<main class="single"><section class="panel"><p class="eyebrow">MAEVE PHONE DASHBOARD / READ ONLY</p>
                <h1>THS DASHBOARD</h1><p class="offline-box">INVENTORY DATABASE UNAVAILABLE</p>
                <a class="back" href="/">BACK TO MAEVE</a></section></main>""",
            )

        cards = (
            ("Active spools", totals["physical_spools"] - totals["archived_spools"]),
            ("Sealed", totals["sealed_spools"]),
            ("Open", totals["open_spools"]),
            ("AMS loaded", totals["loaded_spools"]),
            ("Available filament", f'{float(totals["available_grams"] or 0):,.0f} g'),
            ("AMS occupancy", f'{totals["occupied_slots"]}/{totals["total_slots"]}'),
        )
        card_html = "".join(
            f'<article class="summary-card"><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></article>'
            for label, value in cards
        )
        ams = "".join(
            f"""<li><span>{html.escape(str(slot['equipment']))} / SLOT {int(slot['slot_number'])}</span>
            <strong>{html.escape(str(slot['color'] or 'EMPTY'))}</strong><small>{html.escape(str(slot['manufacturer'] or 'AVAILABLE'))}</small></li>"""
            for slot in totals["ams_details"]
        ) or "<li>NO AMS SLOTS RECORDED</li>"
        orders = "".join(
            f"""<li><span>{html.escape(str(order['supplier']))}</span><strong>{html.escape(str(order['description']))}</strong>
            <small>{html.escape(str(order['state']).upper())}</small></li>"""
            for order in totals["pending_orders"]
        ) or "<li>NO PENDING ORDERS</li>"
        activity = "".join(
            f"""<li><span>{html.escape(str(item['occurred_at']))}</span><strong>{html.escape(str(item['action_type']).replace('_', ' ').upper())}</strong>
            <small>{html.escape(str(item['affected_human_id'] or ''))}</small></li>"""
            for item in totals["recent_activity"]
        ) or "<li>NO RECENT INVENTORY ACTIVITY</li>"
        return self._shell(
            "THS Dashboard",
            f"""<main class="single wide"><section class="panel"><p class="eyebrow">MAEVE PHONE DASHBOARD / READ ONLY</p>
            <h1>THS DASHBOARD</h1><p class="fine">Private phone view. No inventory or printer-changing operation exists on this page.</p>
            <div class="summary-grid">{card_html}</div><div class="actions"><a href="/inventory/filament">FILAMENT INVENTORY</a>
            <a href="/print-library">THS PRINT LIBRARY</a><a href="/">BACK TO MAEVE</a></div></section>
            <section class="dashboard-grid"><article class="panel"><h2>AMS STATUS</h2><ul class="dashboard-list">{ams}</ul></article>
            <article class="panel"><h2>PENDING ORDERS</h2><ul class="dashboard-list">{orders}</ul></article>
            <article class="panel"><h2>RECENT INVENTORY ACTIVITY</h2><ul class="dashboard-list">{activity}</ul></article></section></main>""",
        )

    def _dashboard_read_only_page(self) -> str:
        return self._shell(
            "Dashboard Read-Only Gate",
            """<main class="single"><section class="panel"><p class="eyebrow">MAEVE PHONE VIEW</p>
            <h1>READ-ONLY DASHBOARD</h1><p class="offline-box">THAT WORKFLOW IS BLOCKED ON THE PHONE VIEW</p>
            <p>Use the desktop THS Dashboard when Cowboy intentionally needs an inventory-changing workflow.</p>
            <a class="back" href="/dashboard/">BACK TO DASHBOARD</a><a class="back" href="/">BACK TO MAEVE</a>
            </section></main>""",
        )

    def _filament_inventory_page(self, query: dict[str, list[str]]) -> str:
        search = query.get("q", [""])[-1].strip()
        try:
            data = InventoryQueries(self.paths.database).grouped_filament(search=search)
        except DatabaseNotReady:
            return self._shell(
                "Filament Inventory",
                """<main class="single"><section class="panel"><p class="eyebrow">THS INVENTORY</p>
                <h1>FILAMENT INVENTORY</h1><p class="offline-box">INVENTORY DATABASE UNAVAILABLE</p>
                <a class="back" href="/">BACK TO MAEVE</a></section></main>""",
            )
        products = data["products"]
        cards = "".join(
            f"""<article class="item-card"><h2>{html.escape(str(row['manufacturer']))} &mdash; {html.escape(str(row['color']))}</h2>
            <p>{html.escape(str(row['product_line']))} &bull; {html.escape(str(row['material']))}</p><dl>
            <div><dt>Available</dt><dd>{float(row['available_grams'] or 0):,.0f} g</dd></div>
            <div><dt>Physical spools</dt><dd>{int(row['physical_spools'])}</dd></div>
            <div><dt>Sealed / open / loaded</dt><dd>{int(row['sealed_spools'])} / {int(row['open_spools'])} / {int(row['loaded_spools'])}</dd></div>
            </dl></article>"""
            for row in products
        ) or '<p class="offline-box">NO MATCHING FILAMENT FOUND</p>'
        return self._shell(
            "Filament Inventory",
            f"""<main class="single wide"><section class="panel"><p class="eyebrow">THS INVENTORY / READ ONLY</p>
            <h1>FILAMENT INVENTORY</h1><p class="fine">Live view of the THS inventory database. This page cannot change inventory.</p>
            <form class="search" method="get" action="/inventory/filament"><label for="filament-search">SEARCH</label>
            <div><input id="filament-search" name="q" value="{html.escape(search, quote=True)}" placeholder="Brand, material, color, or spool ID">
            <button type="submit">SEARCH</button></div></form><div class="item-grid">{cards}</div>
            <a class="back" href="/">BACK TO MAEVE</a></section></main>""",
        )

    def _print_library_page(self, query: dict[str, list[str]]) -> str:
        search = query.get("q", [""])[-1].strip().casefold()
        root = self.paths.print_library
        supported = {".3mf", ".stl", ".step", ".stp", ".obj", ".gcode", ".bgcode"}
        entries: list[tuple[str, int]] = []
        if root.is_dir():
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.casefold() not in supported:
                    continue
                relative = str(path.relative_to(root))
                if search and search not in relative.casefold():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                entries.append((relative, size))
                if len(entries) >= 250:
                    break
        rows = "".join(
            f'<tr><td data-label="Project">{html.escape(relative)}</td><td data-label="Type">{html.escape(Path(relative).suffix.upper().lstrip("."))}</td><td data-label="Size">{size / (1024 * 1024):,.1f} MB</td></tr>'
            for relative, size in sorted(entries, key=lambda item: item[0].casefold())
        ) or '<tr><td colspan="3">NO MATCHING PRINT FILES FOUND</td></tr>'
        availability = "AVAILABLE" if root.is_dir() else "LIBRARY UNAVAILABLE"
        return self._shell(
            "THS Print Library",
            f"""<main class="single wide"><section class="panel"><p class="eyebrow">THS PRINT LIBRARY / READ ONLY</p>
            <h1>THS PRINT LIBRARY</h1><p class="ready">{availability}</p>
            <p class="fine">Browser catalog only. This page cannot open, upload, slice, or start a print.</p>
            <form class="search" method="get" action="/print-library"><label for="library-search">SEARCH</label>
            <div><input id="library-search" name="q" value="{html.escape(query.get('q', [''])[-1].strip(), quote=True)}" placeholder="Project, plate, or filename">
            <button type="submit">SEARCH</button></div></form><div class="table-wrap"><table><thead><tr><th>Project file</th><th>Type</th><th>Size</th></tr></thead><tbody>{rows}</tbody></table></div>
            <p class="fine">Showing up to 250 supported print files.</p><a class="back" href="/">BACK TO MAEVE</a></section></main>""",
        )

    def _documentation_page(self) -> str:
        return self._shell(
            "Maeve Status",
            """<main class="single"><section class="panel"><p class="eyebrow">CURRENT FOUNDATION</p>
            <h1>MAEVE STATUS</h1><p>Maeve is local-only and monitoring-only.</p><ul>
            <li>Camera: viewer-driven local adapter with one shared connection maximum.</li>
            <li>MQTT: parked because the current firmware closes authorized report subscriptions.</li>
            <li>Printer control: disabled. No command API exists.</li>
            <li>Inventory: read-only links only.</li>
            <li>Phone and remote access: not exposed.</li></ul><a class="back" href="/">BACK TO CONSOLE</a>
            </section></main>""",
        )

    @staticmethod
    def _shell(title: str, body: str) -> str:
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
        <meta name="theme-color" content="#0d0f11"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Maeve"><link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/assets/maeve-app-icon.svg" type="image/svg+xml">
        <title>{html.escape(title)}</title><style>
        :root{{--orange:#ff6900;--off:#f5f5f5;--gray:#aeb2b6;--panel:#17191c;--track:#282b2e}}
        *{{box-sizing:border-box}}body{{margin:0;background:#0d0f11;color:var(--off);font-family:Bahnschrift,'Segoe UI',sans-serif}}
        body:before{{content:'';position:fixed;inset:0 0 auto 0;height:6px;background:var(--orange)}}
        .hero{{max-width:1260px;margin:28px auto 18px;padding:24px;display:flex;gap:24px;align-items:center;border-left:6px solid var(--orange);background:#141619}}
        .portrait{{width:150px;height:170px;flex:none;background-image:url('/assets/maeve.webp');background-size:800% 1100%;background-position:0 0;background-repeat:no-repeat}}
        h1,h2,p{{margin-top:0}}h1{{font-size:34px;margin-bottom:8px}}h2{{font-size:17px;color:var(--orange);letter-spacing:.08em;border-bottom:1px solid #8a3a00;padding-bottom:10px}}
        .eyebrow,.ready{{color:var(--orange);font-weight:800;letter-spacing:.1em}}.ready{{font-size:20px;margin-bottom:5px}}
        .grid{{max-width:1260px;margin:auto;display:grid;grid-template-columns:1fr 1fr;gap:16px;padding-bottom:36px}}
        .panel{{background:var(--panel);border-left:4px solid var(--orange);padding:20px;min-width:0}}
        .printer-panel{{grid-column:1/-1}}.live-head{{display:flex;justify-content:space-between;align-items:start;gap:14px}}.live-head h2{{flex:1}}.live-head>div{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}}
        .status-badge{{padding:6px 11px;border-radius:999px;font-weight:900;letter-spacing:.08em;background:#555}}.status-badge.live{{background:#147a38}}.status-badge.stale{{background:#a54a00}}.status-badge.offline{{background:#7b1c1c}}.telemetry-age{{color:var(--gray);font-size:12px}}
        .job-name{{font-size:25px;font-weight:900;margin:4px 0 14px;overflow-wrap:anywhere}}.metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.metric{{background:#0f1113;border-top:3px solid var(--orange);padding:13px;min-width:0}}.metric span{{color:var(--gray);font-size:12px;letter-spacing:.08em}}.metric strong{{display:block;font-size:24px;margin-top:6px;overflow-wrap:anywhere}}.progress-track{{height:12px;background:var(--track);margin:13px 0 16px;overflow:hidden}}.progress-fill{{height:100%;background:var(--orange);transition:width .35s ease}}
        h3{{color:var(--gray);font-size:13px;letter-spacing:.09em;margin:18px 0 9px}}.ams-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}.ams-chip{{display:grid;grid-template-columns:auto auto 1fr;align-items:center;gap:7px;background:#0f1113;border:1px solid #34383c;padding:10px;min-width:0}}.ams-chip small{{grid-column:2/-1;color:var(--gray);font-size:10px}}.color-dot{{width:15px;height:15px;border-radius:50%;border:1px solid #777;background:#222}}
        .alert-toolbar{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}.alert-toolbar .fine{{margin:0}}.alert-list{{display:grid;gap:7px;margin-top:9px}}.alert-item{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;background:#0f1113;border-left:4px solid var(--orange);padding:11px}}.alert-item span,.alert-item small{{color:var(--gray)}}.alert-item.complete{{border-left-color:#25a956}}.alert-item.error,.alert-item.offline{{border-left-color:#d43b3b}}.alert-item.paused,.alert-item.warning,.alert-item.stale{{border-left-color:#e89320}}
        dl{{margin:0}}dl div{{display:flex;justify-content:space-between;gap:20px;padding:8px 0;border-bottom:1px solid var(--track)}}dt{{color:var(--gray)}}dd{{margin:0;text-align:right;font-weight:700}}
        .actions{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px}}a{{display:block;background:#292c30;color:var(--off);padding:12px;text-align:center;text-decoration:none;font-weight:800;border:1px solid #3a3e42}}a:hover{{background:var(--orange);color:#111}}
        .camera-frame{{display:none;width:100%;max-height:300px;object-fit:contain;margin-top:16px;background:#090a0b;border:1px solid #3a3e42}}
        .camera-refresh{{background:#292c30;color:var(--off);padding:10px 16px;font:800 14px Bahnschrift,'Segoe UI',sans-serif;border:1px solid #3a3e42;cursor:pointer}}.camera-refresh:hover{{background:var(--orange);color:#111}}
        .offline-box{{padding:40px;text-align:center;color:var(--orange);background:#0c0d0e;margin-top:16px}}.fine{{color:var(--gray);font-size:13px;margin-top:16px}}
        .single{{max-width:900px;margin:50px auto;padding:0 12px}}.single.wide{{max-width:1260px}}ul{{line-height:1.8}}.back{{margin-top:18px}}
        .search{{margin:18px 0}}.search label{{display:block;color:var(--orange);font-weight:800;margin-bottom:7px}}.search div{{display:flex;gap:8px}}.search input{{width:100%;min-width:0;background:#0d0f11;color:var(--off);border:1px solid #3a3e42;padding:12px;font:16px Bahnschrift,'Segoe UI',sans-serif}}.search button{{background:var(--orange);color:#111;border:0;padding:0 18px;font-weight:800;cursor:pointer}}
        .item-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}.item-card{{background:#0f1113;border:1px solid #34383c;border-left:3px solid var(--orange);padding:15px}}.item-card h2{{font-size:15px}}
        .summary-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}}.summary-card{{background:#0f1113;border-left:3px solid var(--orange);padding:14px;display:grid;gap:7px}}.summary-card span{{color:var(--gray)}}.summary-card strong{{font-size:24px}}
        .dashboard-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-top:12px}}.dashboard-list{{list-style:none;padding:0;margin:0}}.dashboard-list li{{display:grid;gap:3px;padding:10px 0;border-bottom:1px solid var(--track)}}.dashboard-list span,.dashboard-list small{{color:var(--gray)}}
        .table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px;border-bottom:1px solid var(--track);text-align:left}}th{{color:var(--orange)}}
        @media(max-width:850px){{.grid{{grid-template-columns:1fr;padding:0 12px 24px}}.hero{{margin:18px 12px}}.portrait{{width:100px;height:120px}}.actions{{grid-template-columns:1fr}}.metric-grid{{grid-template-columns:1fr 1fr}}.metric strong{{font-size:21px}}.ams-grid{{grid-template-columns:1fr 1fr}}.live-head{{display:block}}.live-head>div{{justify-content:flex-start;margin-bottom:12px}}.single{{margin:18px auto}}.search div{{display:grid}}.search button{{padding:12px}}table,thead,tbody,tr,th,td{{display:block}}thead{{display:none}}tr{{padding:8px 0;border-bottom:1px solid var(--track)}}td{{display:flex;justify-content:space-between;gap:16px;border:0;padding:5px}}td:before{{content:attr(data-label);color:var(--gray);font-weight:700}}td[colspan]:before{{content:''}}}}
        </style></head><body>{body}</body></html>"""

    def _manifest(self):
        body = json.dumps({
            "id": "/",
            "name": "Maeve Command Console",
            "short_name": "Maeve",
            "description": "Private THS printer monitoring console.",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#0d0f11",
            "theme_color": "#ff6900",
            "icons": [{"src": "/assets/maeve-app-icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
        }, separators=(",", ":")).encode("utf-8")
        return 200, self._headers("application/manifest+json; charset=utf-8", len(body)), body

    def _service_worker(self):
        body = b"""'use strict';
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let notice = {title:'Maeve Alert', body:'A printer event needs your attention.', kind:'notice'};
  try { if (event.data) notice = Object.assign(notice, event.data.json()); } catch (_) {}
  event.waitUntil(self.registration.showNotification(notice.title, {
    body: notice.body, tag: notice.kind, icon:'/assets/maeve-app-icon.svg', badge:'/assets/maeve-app-icon.svg', data:{url:'/'}, renotify:true
  }));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.matchAll({type:'window', includeUncontrolled:true}).then(windows => {
    for (const windowClient of windows) { if ('focus' in windowClient) return windowClient.focus(); }
    return clients.openWindow('/');
  }));
});
"""
        return 200, self._headers("application/javascript; charset=utf-8", len(body)), body

    def _app_icon(self):
        body = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="96" fill="#0d0f11"/><path d="M0 0h512v28H0zM0 0h28v512H0z" fill="#f5f5f5"/><path d="M104 374V138h66l86 118 86-118h66v236h-70V244l-82 110-82-110v130z" fill="#ff6900"/><path d="M104 402h304v18H104z" fill="#f5f5f5"/></svg>"""
        return 200, self._headers("image/svg+xml; charset=utf-8", len(body)), body

    @staticmethod
    def _headers(content_type: str, length: int) -> list[tuple[str, str]]:
        return [("Content-Type", content_type), ("Content-Length", str(length)), ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"), ("Pragma", "no-cache"), ("Expires", "0"), ("X-Content-Type-Options", "nosniff")]

    def _html(self, status: int, text: str):
        body = text.encode("utf-8")
        return status, self._headers("text/html; charset=utf-8", len(body)), body

    def _json(self, status: int, value: dict[str, object]):
        body = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
        return status, self._headers("application/json; charset=utf-8", len(body)), body

    def _text(self, status: int, text: str):
        body = (text + "\n").encode("utf-8")
        return status, self._headers("text/plain; charset=utf-8", len(body)), body

    @staticmethod
    def _same_origin(headers) -> bool:
        origin = headers.get("Origin", "")
        host = headers.get("Host", "")
        parsed = urlsplit(origin)
        return parsed.scheme == "https" and parsed.netloc == host


class LoopbackConsoleServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if not ipaddress.ip_address(self.server_address[0]).is_loopback:
            raise RuntimeError("Maeve console may bind only to loopback")
        super().server_bind()


def handler(app: MaeveConsoleApp):
    class Handler(BaseHTTPRequestHandler):
        def _respond(self):
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                self.send_error(403)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > 8192:
                self.send_error(413)
                return
            request_body = self.rfile.read(length) if length else b""
            status, headers, body = app.response(self.path, method=self.command, request_headers=self.headers, request_body=request_body)
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = _respond
        do_HEAD = _respond
        do_POST = _respond
        do_PUT = _respond
        do_PATCH = _respond
        do_DELETE = _respond

        def log_message(self, *_args):
            return

    return Handler
