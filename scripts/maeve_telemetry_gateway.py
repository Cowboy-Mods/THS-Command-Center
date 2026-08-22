from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.maeve_telemetry import (
    AtomicTelemetryStore,
    FixtureProvider,
    OfflineProvider,
    rainmeter_line,
    write_rainmeter_feed,
)


class LoopbackServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if self.server_address[0] not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("Maeve telemetry gateway may bind only to localhost")
        super().server_bind()


def handler(store: AtomicTelemetryStore):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            snapshot = store.read().with_freshness()
            if self.path == "/health":
                self._send("application/json", json.dumps({"status": "ok", "control_capable": False}) + "\n")
            elif self.path == "/status":
                self._send("application/json", json.dumps(snapshot.as_dict(), sort_keys=True) + "\n")
            elif self.path == "/rainmeter":
                self._send("text/plain", rainmeter_line(snapshot))
            else:
                self.send_error(404)

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            self.send_error(405)

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

        def _send(self, content_type: str, text: str):
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def log_message(self, *_args):
            return

    return Handler


def provider(args):
    if args.fixture:
        return FixtureProvider(Path(args.fixtures), args.fixture)
    return OfflineProvider()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local read-only Maeve telemetry gateway")
    parser.add_argument("action", choices=("snapshot", "serve"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--rainmeter-feed", type=Path)
    parser.add_argument("--fixture")
    parser.add_argument("--fixtures", default=ROOT / "tests" / "fixtures" / "maeve_print_watch_states.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=48175)
    args = parser.parse_args(argv)
    snapshot = provider(args).observe()
    store = AtomicTelemetryStore(args.state)
    store.write(snapshot)
    if args.rainmeter_feed:
        write_rainmeter_feed(args.rainmeter_feed, snapshot)
    if args.action == "snapshot":
        print(json.dumps({"mode": snapshot.display_mode, "state": str(args.state), "control_capable": False}))
        return 0
    with LoopbackServer((args.host, args.port), handler(store)) as server:
        server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
