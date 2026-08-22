from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .p1s_camera import CameraSession, CameraValidationError, write_validated_frame


VIEWER_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class OnDemandCameraAdapter:
    """One shared, viewer-driven, read-only P1S camera connection."""

    def __init__(
        self,
        *,
        host: str,
        frame_path: Path,
        initial_result_path: Path,
        credential_loader: Callable[[], str],
        viewer_timeout_seconds: float = 20.0,
        min_frame_interval_seconds: float = 2.0,
        session_factory: Callable[[str, str], CameraSession] = CameraSession,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._host = host
        self._frame_path = frame_path
        self._credential_loader = credential_loader
        self._viewer_timeout = viewer_timeout_seconds
        self._min_frame_interval = min_frame_interval_seconds
        self._session_factory = session_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._viewers: dict[str, float] = {}
        self._attempted_viewers: set[str] = set()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._session: CameraSession | None = None
        self._state = "STALE" if frame_path.is_file() else "OFFLINE"
        self._last_frame = self._initial_timestamp(initial_result_path)
        self._last_error: str | None = None
        self._connection_attempts = 0
        self._active_connections = 0
        self._maximum_connections = 0
        self._frames_received = 0
        self._session_frames = 0
        self._session_timestamps: set[str] = set()
        self._frame_version = 0
        self._delivered_frame_version = 0
        self._last_frame_monotonic: float | None = None
        self._live_threshold_seconds = max(6.0, min_frame_interval_seconds * 3.0)
        self._released_for_studio = False
        self._studio_running = False

    def touch_viewer(self, viewer_id: str) -> dict[str, object]:
        if not VIEWER_ID.fullmatch(viewer_id):
            return self.status()
        with self._lock:
            now = self._clock()
            self._prune_viewers(now)
            self._viewers[viewer_id] = now
            if self._released_for_studio:
                if self._studio_running:
                    return self._status_locked()
                self._released_for_studio = False
                self._state = "STALE" if self._frame_path.is_file() else "OFFLINE"
                self._attempted_viewers.clear()
            alive = self._worker is not None and self._worker.is_alive()
            if not alive and viewer_id not in self._attempted_viewers:
                self._attempted_viewers.update(self._viewers)
                self._stop = threading.Event()
                self._state = "CONNECTING"
                self._worker = threading.Thread(target=self._run, name="MaeveP1SCamera", daemon=True)
                self._worker.start()
            return self._status_locked()

    def status(self) -> dict[str, object]:
        with self._lock:
            self._prune_viewers(self._clock())
            return self._status_locked()

    def mark_frame_delivered(self, frame_version: int) -> None:
        """Record successful browser delivery without starting another connection."""
        with self._lock:
            if frame_version == self._frame_version and frame_version > 0:
                self._delivered_frame_version = frame_version

    def release_for_bambu_studio(self) -> bool:
        with self._lock:
            self._released_for_studio = True
            self._studio_running = True
            self._state = "RELEASED FOR BAMBU STUDIO"
            self._viewers.clear()
        self._stop_and_join()
        with self._lock:
            return self._active_connections == 0

    def mark_bambu_studio_exited(self) -> None:
        with self._lock:
            self._studio_running = False

    def shutdown(self) -> bool:
        with self._lock:
            self._viewers.clear()
        self._stop_and_join()
        with self._lock:
            if not self._released_for_studio:
                self._state = "STALE" if self._frame_path.is_file() else "OFFLINE"
            return self._active_connections == 0

    def _run(self) -> None:
        session = None
        try:
            secret = self._credential_loader()
            with self._lock:
                self._connection_attempts += 1
            session = self._session_factory(self._host, secret)
            secret = ""
            session.open(timeout_seconds=5.0)
            with self._lock:
                self._session = session
                self._active_connections += 1
                self._maximum_connections = max(self._maximum_connections, self._active_connections)
                self._session_frames = 0
                self._session_timestamps.clear()
                self._delivered_frame_version = 0
            last_saved = 0.0
            while not self._stop.is_set():
                with self._lock:
                    now = self._clock()
                    self._prune_viewers(now)
                    if not self._viewers:
                        break
                frame = session.read_frame(timeout_seconds=min(5.0, self._viewer_timeout))
                now = self._clock()
                if now - last_saved >= self._min_frame_interval:
                    write_validated_frame(self._frame_path, frame)
                    last_saved = now
                    with self._lock:
                        self._frames_received += 1
                        self._session_frames += 1
                        self._frame_version += 1
                        self._last_frame = datetime.now(timezone.utc).isoformat()
                        self._session_timestamps.add(self._last_frame)
                        self._last_frame_monotonic = now
                        self._last_error = None
                        self._state = "CONNECTING"
        except CameraValidationError as exc:
            with self._lock:
                self._last_error = exc.category
                self._state = "STALE" if self._frame_path.is_file() else "OFFLINE"
        except Exception:
            with self._lock:
                self._last_error = "camera_adapter_failed"
                self._state = "STALE" if self._frame_path.is_file() else "OFFLINE"
        finally:
            if session is not None:
                session.close()
            with self._lock:
                self._session = None
                self._active_connections = max(0, self._active_connections - 1)
                if self._released_for_studio:
                    self._state = "RELEASED FOR BAMBU STUDIO"
                elif self._state in {"CONNECTING", "LIVE"}:
                    self._state = "STALE"

    def _stop_and_join(self) -> None:
        self._stop.set()
        with self._lock:
            session = self._session
            worker = self._worker
        if session is not None:
            session.close()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=7.0)

    def _prune_viewers(self, now: float) -> None:
        expired = [key for key, seen in self._viewers.items() if now - seen > self._viewer_timeout]
        for key in expired:
            self._viewers.pop(key, None)

    def _status_locked(self) -> dict[str, object]:
        now = self._clock()
        frame_age = None if self._last_frame_monotonic is None else max(0.0, now - self._last_frame_monotonic)
        browser_has_current_frame = self._frame_version > 0 and self._delivered_frame_version == self._frame_version
        if not self._released_for_studio and self._active_connections > 0:
            self._state = "LIVE" if (
                self._session_frames >= 2
                and len(self._session_timestamps) >= 2
                and browser_has_current_frame
                and frame_age is not None
                and frame_age <= self._live_threshold_seconds
            ) else "CONNECTING"
        return {
            "state": self._state,
            "available": self._frame_path.is_file(),
            "last_frame": self._last_frame,
            "viewer_count": len(self._viewers),
            "active_connections": self._active_connections,
            "maximum_connections": self._maximum_connections,
            "connection_attempts": self._connection_attempts,
            "frames_received": self._frames_received,
            "session_frames": self._session_frames,
            "frame_version": self._frame_version,
            "browser_has_current_frame": browser_has_current_frame,
            "frame_age_seconds": None if frame_age is None else round(frame_age, 1),
            "released_for_bambu_studio": self._released_for_studio,
            "studio_running": self._studio_running,
            "control_capable": False,
        }

    @staticmethod
    def _initial_timestamp(path: Path) -> str | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            timestamp = value.get("captured_at")
            return timestamp if isinstance(timestamp, str) else None
        except (OSError, json.JSONDecodeError):
            return None
