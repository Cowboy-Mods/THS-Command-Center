import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from inventory.db import connect, migrate
from inventory.maeve_console import ConsolePaths, LocalActionLauncher, LoopbackConsoleServer, MaeveConsoleApp, ReadOnlyAlertTracker, handler
from inventory.maeve_telemetry import AtomicTelemetryStore, MaeveTelemetry, OfflineProvider


class FakeLauncher:
    def __init__(self):
        self.opened = []

    def open(self, name, target):
        self.opened.append((name, target))
        return target.exists()


class FakeCameraAdapter:
    def __init__(self, frame_exists=True):
        self.frame_exists = frame_exists
        self.touches = []
        self.released = False

    def status(self):
        return {"state": "STALE", "available": self.frame_exists, "last_frame": "TEST", "control_capable": False}

    def touch_viewer(self, viewer):
        self.touches.append(viewer)
        return self.status()

    def mark_frame_delivered(self, frame_version):
        self.delivered = frame_version

    def release_for_bambu_studio(self):
        self.released = True
        return True

    def mark_bambu_studio_exited(self):
        self.exited = True


class FakeProcess:
    def wait(self):
        return 0


class FakePushService:
    def __init__(self):
        self.saved = []

    def public_key(self):
        return "B" + "A" * 86

    def save_subscription(self, value):
        self.saved.append(value)

    def status(self):
        return {"configured": bool(self.saved), "background_capable": True}


class MaeveConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        for name in ("library",):
            (root / name).mkdir()
        for name in ("db.sqlite3", "bambu.exe", "dashboard.cmd", "docs.md", "maeve.webp"):
            (root / name).write_bytes(b"fixture")
        state = root / "state.json"
        AtomicTelemetryStore(state).write(OfflineProvider().observe())
        camera = root / "camera.json"
        camera.write_text(json.dumps({"attempt_count": 1, "frame_received": True, "jpeg_valid": True, "commands_sent": 0, "control_capable": False, "captured_at": "TEST"}), encoding="utf-8")
        (root / "frame.jpg").write_bytes(b"\xff\xd8fixture\xff\xd9")
        paths = ConsolePaths(state, camera, root / "frame.jpg", root / "maeve.webp", root / "db.sqlite3", root / "library", root / "bambu.exe", root / "dashboard.cmd", root / "docs.md")
        self.launcher = FakeLauncher()
        self.camera = FakeCameraAdapter()
        self.push = FakePushService()
        self.app = MaeveConsoleApp(paths, self.camera, self.launcher, push_service=self.push)
        self.server = LoopbackConsoleServer(("127.0.0.1", 0), handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_honest_console_and_status(self):
        page = urllib.request.urlopen(self.base + "/").read().decode()
        self.assertIn("MAEVE COMMAND CONSOLE", page)
        self.assertIn("FARM MANAGER / READ ONLY", page)
        self.assertIn("NOT REPORTED", page)
        status = json.load(urllib.request.urlopen(self.base + "/api/status"))
        self.assertFalse(status["control_capable"])
        self.assertFalse(status["remote_access"])
        self.assertEqual(status["telemetry_state"], "OFFLINE / FARM MANAGER")

        page = urllib.request.urlopen(self.base + "/").read().decode("utf-8")
        self.assertIn('id="telemetry-state"', page)
        self.assertIn('id="ams-loaded"', page)
        self.assertIn('id="live-badge"', page)
        self.assertIn('id="progress-fill"', page)
        self.assertIn('id="ams-swatches"', page)
        self.assertIn("fetch('/api/status'", page)
        self.assertIn("setInterval(pollTelemetry, 2000)", page)
        self.assertIn("CAMERA STALE", page)
        self.assertIn("progress_percent", status)
        self.assertIn("data_age_seconds", status)
        self.assertIsInstance(status["ams_slots"], list)
        self.assertTrue(status["alerts_read_only"])
        self.assertIn('id="alert-list"', page)
        self.assertIn('id="enable-alerts"', page)
        self.assertIn('id="enable-background-alerts"', page)
        self.assertIn('rel="manifest" href="/manifest.webmanifest"', page)
        self.assertIn("navigator.serviceWorker.register('/service-worker.js'", page)

    def test_installable_pwa_assets_are_same_origin_and_read_only(self):
        manifest_response = urllib.request.urlopen(self.base + "/manifest.webmanifest")
        manifest = json.load(manifest_response)
        self.assertEqual(manifest_response.headers["Content-Type"], "application/manifest+json; charset=utf-8")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        worker = urllib.request.urlopen(self.base + "/service-worker.js").read().decode()
        self.assertIn("self.addEventListener('push'", worker)
        self.assertIn("showNotification", worker)
        self.assertNotIn("fetch(", worker)
        icon = urllib.request.urlopen(self.base + "/assets/maeve-app-icon.svg")
        self.assertEqual(icon.headers["Content-Type"], "image/svg+xml; charset=utf-8")
        self.assertIn(b"#ff6900", icon.read())

    def test_background_subscription_requires_same_origin_and_csrf(self):
        body = json.dumps({"endpoint": "https://push.example.test/x", "keys": {"p256dh": "A" * 32, "auth": "B" * 24}}).encode()
        status, _, _ = self.app.response("/api/push-subscription", method="POST", request_body=body)
        self.assertEqual(status, 403)
        status, _, _ = self.app.response(
            "/api/push-subscription", method="POST",
            request_headers={"Origin": "https://maeve.test", "Host": "maeve.test", "X-Maeve-CSRF": self.app._csrf_token},
            request_body=body,
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.push.saved), 1)

    def test_read_only_alert_tracker_detects_transitions_once(self):
        tracker = ReadOnlyAlertTracker()
        printing = MaeveTelemetry(connection_state="online", printer_state="printing", display_mode="LIVE", offline=False, stale=False)
        finished = MaeveTelemetry(connection_state="online", printer_state="finished", display_mode="LIVE", offline=False, stale=False)
        self.assertEqual(tracker.observe(printing), [])
        alerts = tracker.observe(finished)
        self.assertEqual(alerts[0]["kind"], "complete")
        self.assertEqual(len(tracker.observe(finished)), 1)

    def test_read_only_alert_tracker_detects_pause_stale_disconnect_and_error(self):
        tracker = ReadOnlyAlertTracker()
        live = MaeveTelemetry(connection_state="online", printer_state="printing", display_mode="LIVE", offline=False, stale=False)
        paused = MaeveTelemetry(connection_state="online", printer_state="paused", display_mode="LIVE", offline=False, stale=False)
        stale = MaeveTelemetry(connection_state="online", printer_state="paused", display_mode="STALE", offline=False, stale=True)
        offline = MaeveTelemetry(connection_state="offline", printer_state="offline", display_mode="OFFLINE", offline=True, stale=True)
        error = MaeveTelemetry(connection_state="online", printer_state="error", display_mode="LIVE", offline=False, stale=False, warning_code="SAFE", warning_text="Sanitized warning")
        tracker.observe(live)
        self.assertEqual(tracker.observe(paused)[0]["kind"], "paused")
        self.assertEqual(tracker.observe(stale)[0]["kind"], "stale")
        self.assertEqual(tracker.observe(offline)[0]["kind"], "offline")
        kinds = [item["kind"] for item in tracker.observe(error)]
        self.assertIn("error", kinds)
        self.assertIn("warning", kinds)

    def test_read_only_alert_tracker_emits_each_progress_milestone_once(self):
        tracker = ReadOnlyAlertTracker()
        def printing(progress):
            return MaeveTelemetry(connection_state="online", printer_state="printing", display_mode="LIVE", offline=False, stale=False, progress_percent=progress)
        self.assertEqual(tracker.observe(printing(24)), [])
        self.assertEqual(tracker.observe(printing(25))[0]["kind"], "milestone-25")
        self.assertEqual(len(tracker.observe(printing(49))), 1)
        self.assertEqual(tracker.observe(printing(50))[0]["kind"], "milestone-50")
        self.assertEqual(len(tracker.observe(printing(60))), 2)
        self.assertEqual(tracker.observe(printing(76))[0]["kind"], "milestone-75")
        self.assertEqual(len(tracker.observe(printing(80))), 3)

    def test_read_only_alert_tracker_emits_first_layer_only_on_observed_transition(self):
        tracker = ReadOnlyAlertTracker()
        def printing(layer):
            return MaeveTelemetry(connection_state="online", printer_state="printing", display_mode="LIVE", offline=False, stale=False, current_layer=layer)
        self.assertEqual(tracker.observe(printing(1)), [])
        self.assertEqual(tracker.observe(printing(1)), [])
        self.assertEqual(tracker.observe(printing(2))[0]["kind"], "first-layer-complete")
        self.assertEqual(len(tracker.observe(printing(3))), 1)

        restarted = ReadOnlyAlertTracker()
        self.assertEqual(restarted.observe(printing(2)), [])
        self.assertEqual(restarted.observe(printing(3)), [])

    def test_camera_route_tracks_viewer_without_exposing_private_configuration(self):
        camera = json.load(urllib.request.urlopen(self.base + "/api/camera?viewer=viewer_12345"))
        self.assertEqual(camera["state"], "STALE")
        self.assertEqual(self.camera.touches, ["viewer_12345"])
        body = urllib.request.urlopen(self.base + "/camera/frame.jpg?viewer=viewer_12345").read()
        self.assertTrue(body.startswith(b"\xff\xd8"))
        image_response = urllib.request.urlopen(self.base + "/camera/frame.jpg?viewer=viewer_12345")
        self.assertIn("no-cache", image_response.headers["Cache-Control"])
        self.assertEqual(image_response.headers["Pragma"], "no-cache")
        self.assertIn("REFRESH CAMERA", urllib.request.urlopen(self.base + "/").read().decode())
        response = json.dumps(camera).casefold()
        for prohibited in ("access_code", "password", "serial", "printer_host", "192.168"):
            self.assertNotIn(prohibited, response)

    def test_camera_page_suppresses_only_normal_live_frame_handoff_flicker(self):
        page = urllib.request.urlopen(self.base + "/").read().decode()
        self.assertIn("normalFrameHandoff", page)
        self.assertIn("deliveredLive && camera.state === 'CONNECTING'", page)
        self.assertIn("frame.addEventListener('error'", page)
        self.assertIn("deliveredLive = false", page)

    def test_get_only_and_no_control_routes(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(self.base + "/api/status", method=method))
            self.assertEqual(error.exception.code, 405)
        for forbidden in ("/pause", "/resume", "/cancel", "/print", "/api/control"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + forbidden)
            self.assertEqual(error.exception.code, 404)

    def test_non_loopback_bind_is_rejected(self):
        with self.assertRaises(RuntimeError):
            LoopbackConsoleServer(("0.0.0.0", 0), handler(self.app))

    def test_local_actions_are_fixed_allowlist(self):
        result = json.load(urllib.request.urlopen(self.base + "/launch/bambu-studio"))
        self.assertTrue(result["opened"])
        self.assertEqual(len(self.launcher.opened), 1)
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(self.base + "/launch/arbitrary")
        self.assertEqual(error.exception.code, 404)

    def test_phone_navigation_uses_read_only_browser_routes(self):
        page = urllib.request.urlopen(self.base + "/").read().decode()
        self.assertIn('href="/inventory/filament"', page)
        self.assertIn('href="/print-library"', page)
        self.assertNotIn('href="/launch/print-library"', page)
        self.assertIn("DESKTOP: OPEN BAMBU STUDIO", page)

        self.app.paths.database.unlink()
        filament = urllib.request.urlopen(self.base + "/inventory/filament").read().decode()
        self.assertIn("FILAMENT INVENTORY", filament)
        self.assertIn("INVENTORY DATABASE UNAVAILABLE", filament)
        self.assertNotIn("/launch/", filament)

        library = urllib.request.urlopen(self.base + "/print-library").read().decode()
        self.assertIn("THS PRINT LIBRARY", library)
        self.assertIn("Browser catalog only", library)
        self.assertNotIn("/launch/", library)

    def test_phone_routes_do_not_launch_windows_actions(self):
        self.app.paths.database.unlink()
        urllib.request.urlopen(self.base + "/inventory/filament").read()
        urllib.request.urlopen(self.base + "/print-library").read()
        self.assertEqual(self.launcher.opened, [])

    def test_print_library_filters_supported_files_without_serving_them(self):
        (self.app.paths.print_library / "Lamppost Plate 3.3mf").write_bytes(b"fixture")
        (self.app.paths.print_library / "notes.txt").write_text("not a print", encoding="utf-8")
        page = urllib.request.urlopen(self.base + "/print-library?q=plate%203").read().decode()
        self.assertIn("Lamppost Plate 3.3mf", page)
        self.assertNotIn("notes.txt", page)

    def test_phone_dashboard_is_same_origin_and_read_only(self):
        self.app.paths.database.unlink()
        db = connect(self.app.paths.database)
        migrate(db)
        db.close()

        home = urllib.request.urlopen(self.base + "/").read().decode()
        self.assertIn('href="/dashboard/"', home)
        self.assertNotIn('href="/launch/dashboard"', home)

        dashboard = urllib.request.urlopen(self.base + "/dashboard/").read().decode()
        self.assertIn("THS DASHBOARD", dashboard)
        self.assertIn("MAEVE PHONE DASHBOARD", dashboard)
        self.assertIn("READ ONLY", dashboard)
        self.assertIn('href="/inventory/filament"', dashboard)
        self.assertIn('href="/print-library"', dashboard)
        self.assertNotIn("<form", dashboard)
        self.assertNotIn("/launch/", dashboard)
        self.assertEqual(self.launcher.opened, [])

    def test_phone_dashboard_blocks_mutation_routes_and_methods(self):
        blocked_gets = (
            "/dashboard/inventory/filament/receive",
            "/dashboard/inventory/filament/replace",
            "/dashboard/inventory/filament/ams/initialize",
            "/dashboard/inventory/filament/ams/return",
            "/dashboard/inventory/filament/register-open",
            "/dashboard/prints/complete",
            "/dashboard/maintenance/action",
            "/dashboard/maintenance/evidence",
            "/dashboard/orders/1/receive",
        )
        for route in blocked_gets:
            with self.subTest(route=route), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(self.base + route)
            self.assertEqual(error.exception.code, 403)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            request = urllib.request.Request(self.base + "/dashboard/", method=method)
            with self.subTest(method=method), self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 405)

    def test_bambu_studio_launcher_releases_camera_before_process_start(self):
        order = []
        camera = FakeCameraAdapter()
        camera.release_for_bambu_studio = lambda: order.append("release") or True
        camera.mark_bambu_studio_exited = lambda: order.append("exit")
        launcher = LocalActionLauncher(camera, process_factory=lambda *_args, **_kwargs: order.append("launch") or FakeProcess())
        self.assertTrue(launcher.open("bambu-studio", self.app.paths.bambu_studio))
        self.assertEqual(order[:2], ["release", "launch"])


if __name__ == "__main__":
    unittest.main()
