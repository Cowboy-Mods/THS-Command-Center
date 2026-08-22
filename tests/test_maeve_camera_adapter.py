import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from inventory.maeve_camera_adapter import OnDemandCameraAdapter
from inventory.p1s_camera import CameraFrame, CameraValidationError


FRAME = CameraFrame(bytes.fromhex("FFD8FFC0000B0802D0050001011100FFD9"), 1280, 720, "TLSv1.2", "TEST")


class FakeSession:
    active = 0
    maximum = 0
    opens = 0
    fail = False
    lock = threading.Lock()

    def __init__(self, _host, _secret):
        self.closed = threading.Event()

    def open(self, timeout_seconds=5):
        with self.lock:
            type(self).opens += 1
            type(self).active += 1
            type(self).maximum = max(type(self).maximum, type(self).active)

    def read_frame(self, timeout_seconds=5):
        if self.fail:
            raise CameraValidationError("synthetic_failure", "camera_capture")
        if self.closed.wait(0.02):
            raise CameraValidationError("connection_closed", "camera_capture")
        return FRAME

    def close(self):
        if not self.closed.is_set():
            self.closed.set()
            with self.lock:
                type(self).active = max(0, type(self).active - 1)


class FakeProcess:
    def wait(self):
        return 0


class MaeveCameraAdapterTests(unittest.TestCase):
    def setUp(self):
        FakeSession.active = FakeSession.maximum = FakeSession.opens = 0
        FakeSession.fail = False
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.frame = root / "frame.jpg"
        result = root / "result.json"
        result.write_text(json.dumps({"captured_at": "INITIAL"}), encoding="utf-8")
        self.adapter = OnDemandCameraAdapter(host="192.0.2.10", frame_path=self.frame, initial_result_path=result, credential_loader=lambda: "FAKECODE", viewer_timeout_seconds=0.25, min_frame_interval_seconds=0.05, session_factory=FakeSession)

    def tearDown(self):
        self.adapter.shutdown()
        self.temp.cleanup()

    def wait_for(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(0.01)
        self.fail("condition not reached")

    def test_two_viewers_share_one_connection_and_idle_release(self):
        self.adapter.touch_viewer("viewer_one")
        self.adapter.touch_viewer("viewer_two")
        self.wait_for(lambda: self.adapter.status()["frames_received"] >= 2)
        self.assertEqual(FakeSession.maximum, 1)
        self.assertEqual(self.adapter.status()["state"], "CONNECTING")
        self.adapter.mark_frame_delivered(self.adapter.status()["frame_version"])
        self.assertEqual(self.adapter.status()["state"], "LIVE")
        self.wait_for(lambda: self.adapter.status()["active_connections"] == 0)
        self.assertEqual(self.adapter.status()["state"], "STALE")

    def test_failure_retains_last_frame_as_stale_without_retry(self):
        self.frame.write_bytes(FRAME.jpeg)
        FakeSession.fail = True
        self.adapter.touch_viewer("viewer_failure")
        self.wait_for(lambda: FakeSession.opens == 1 and self.adapter.status()["active_connections"] == 0)
        for _ in range(4): self.adapter.touch_viewer("viewer_failure")
        time.sleep(0.05)
        self.assertEqual(FakeSession.opens, 1)
        self.assertEqual(self.adapter.status()["state"], "STALE")

    def test_live_requires_two_frames_and_current_browser_delivery(self):
        self.adapter.touch_viewer("viewer_gate")
        self.wait_for(lambda: self.adapter.status()["frames_received"] >= 1)
        first = self.adapter.status()
        self.assertEqual(first["state"], "CONNECTING")
        self.adapter.mark_frame_delivered(first["frame_version"])
        self.assertEqual(self.adapter.status()["state"], "CONNECTING")
        self.wait_for(lambda: self.adapter.status()["frames_received"] >= 2)
        second = self.adapter.status()
        self.assertFalse(second["browser_has_current_frame"])
        self.adapter.mark_frame_delivered(second["frame_version"])
        live = self.adapter.status()
        self.assertEqual(live["state"], "LIVE")
        self.assertTrue(live["browser_has_current_frame"])

    def test_failure_without_any_valid_frame_is_offline(self):
        FakeSession.fail = True
        self.adapter.touch_viewer("viewer_offline")
        self.wait_for(lambda: FakeSession.opens == 1 and self.adapter.status()["active_connections"] == 0)
        self.assertEqual(self.adapter.status()["state"], "OFFLINE")
        self.assertFalse(self.adapter.status()["available"])

    def test_release_for_studio_closes_camera_and_requires_new_view_activity(self):
        self.adapter.touch_viewer("viewer_before")
        self.wait_for(lambda: self.adapter.status()["active_connections"] == 1)
        self.assertTrue(self.adapter.release_for_bambu_studio())
        self.assertEqual(self.adapter.status()["state"], "RELEASED FOR BAMBU STUDIO")
        self.assertEqual(self.adapter.status()["active_connections"], 0)
        self.adapter.mark_bambu_studio_exited()
        time.sleep(0.05)
        self.assertEqual(FakeSession.opens, 1)
        self.adapter.touch_viewer("viewer_after")
        self.wait_for(lambda: FakeSession.opens == 2)


if __name__ == "__main__":
    unittest.main()
