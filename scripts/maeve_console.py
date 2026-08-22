from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUNTIME_PACKAGES = Path.home() / "Documents" / "THS-Command-Center-Data" / "runtime" / "python-packages"
if RUNTIME_PACKAGES.is_dir():
    sys.path.insert(0, str(RUNTIME_PACKAGES))

from inventory.maeve_console import ConsolePaths, LoopbackConsoleServer, MaeveConsoleApp, handler
from inventory.maeve_camera_adapter import OnDemandCameraAdapter
from inventory.maeve_push import ProtectedWebPushService
from inventory.credentials import load_p1s_access_code
from inventory.maeve_local_config import load_printer_host


def default_paths() -> ConsolePaths:
    home = Path.home()
    runtime = home / "Documents" / "THS-Command-Center-Data" / "runtime"
    camera = runtime / "camera-validation"
    return ConsolePaths(
        telemetry_state=runtime / "maeve-telemetry.json",
        camera_result=camera / "maeve-p1s-camera-result.json",
        camera_frame=camera / "maeve-p1s-validation-frame.jpg",
        maeve_art=home / ".codex" / "pets" / "maeve" / "spritesheet.webp",
        database=home / "Documents" / "THS-Command-Center-Data" / "inventory.sqlite3",
        print_library=Path(r"C:\THS\3D Printing\THS 3D Printing Library"),
        bambu_studio=Path(r"C:\Bambu Studio\bambu-studio.exe"),
        dashboard_launcher=ROOT / "Start THS Dashboard.cmd",
        documentation=ROOT / "docs" / "inventory-system" / "MAEVE_LOCAL_CONSOLE_FOUNDATION.md",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local-only Maeve command console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=48176)
    parser.add_argument("--stop-signal", type=Path)
    args = parser.parse_args(argv)
    paths = default_paths()
    adapter = OnDemandCameraAdapter(
        host=load_printer_host(),
        frame_path=paths.camera_frame,
        initial_result_path=paths.camera_result,
        credential_loader=load_p1s_access_code,
        viewer_timeout_seconds=20.0,
        min_frame_interval_seconds=2.0,
    )
    push_service = ProtectedWebPushService(paths.telemetry_state.parent)
    app = MaeveConsoleApp(paths, adapter, push_service=push_service)
    if args.stop_signal:
        args.stop_signal.unlink(missing_ok=True)
    with LoopbackConsoleServer((args.host, args.port), handler(app)) as server:
        watcher = None
        if args.stop_signal:
            def watch_stop_signal():
                while not args.stop_signal.exists():
                    time.sleep(0.2)
                adapter.shutdown()
                server.shutdown()
            watcher = threading.Thread(target=watch_stop_signal, name="MaeveStopSignal", daemon=True)
            watcher.start()
        try:
            def watch_alerts():
                while not (args.stop_signal and args.stop_signal.exists()):
                    try:
                        push_service.send_pending(app.status()["alerts"])
                    except Exception:
                        pass
                    time.sleep(5)
            threading.Thread(target=watch_alerts, name="MaeveReadOnlyPush", daemon=True).start()
            server.serve_forever(poll_interval=0.25)
        finally:
            adapter.shutdown()
            if args.stop_signal:
                args.stop_signal.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
