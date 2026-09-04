"""Transparent Windows launcher for the Maeve V2 Stage 13 runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.request


RUNTIME_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RUNTIME_ROOT))
from runtime_config import export_environment, load_config
PYTHON_EXE = Path("python.exe")
WSL_EXE = Path(r"C:\Windows\System32\wsl.exe")
EDGE_EXE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
SERVER = RUNTIME_ROOT / "broker" / "server.py"
HOST = "127.0.0.1"
PORT = 48177
RESERVED_PORT = 48178
TOKEN_ENV = "MAEVE_RUNTIME_TOKEN"
STARTUP_DEADLINE_SECONDS = 120.0
READINESS_POLL_INTERVAL_SECONDS = 0.2
REQUIRED_FILES = (
    SERVER,
    RUNTIME_ROOT / "ui" / "index.html",
    RUNTIME_ROOT / "ui" / "scripts" / "ptt-controller.js",
    RUNTIME_ROOT / "ui" / "scripts" / "conversation-controller.js",
    RUNTIME_ROOT / "worker" / "stt_worker.py",
    RUNTIME_ROOT / "worker" / "qwen_worker.py",
    RUNTIME_ROOT / "worker" / "reasoner_worker.py",
    RUNTIME_ROOT / "broker" / "conversation_policy.py",
    RUNTIME_ROOT / "broker" / "model_scheduler.py",
    RUNTIME_ROOT / "broker" / "voice_provider.py",
)
ENV_ALLOWLIST = (
    "APPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "USERNAME",
    "WINDIR",
)


class OwnedChildren:
    """Track only direct children returned by this launcher."""

    def __init__(self) -> None:
        self._children: dict[int, subprocess.Popen[bytes]] = {}

    def start(self, arguments: list[str], *, cwd: Path, env: dict[str, str],
              capture: bool = False, process_group: bool = False) -> subprocess.Popen[bytes]:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if process_group else 0
        process = subprocess.Popen(
            arguments,
            cwd=str(cwd),
            env=env,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            creationflags=flags,
        )
        self._children[process.pid] = process
        return process

    def forget_if_exited(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            self._children.pop(process.pid, None)

    def stop_exact(self, process: subprocess.Popen[bytes], *, graceful_break: bool) -> str:
        if self._children.get(process.pid) is not process:
            raise RuntimeError("Cleanup rejected an unowned process handle")
        if process.poll() is not None:
            self._children.pop(process.pid, None)
            return "already-exited"
        if graceful_break:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                process.wait(timeout=8)
                self._children.pop(process.pid, None)
                return "graceful-break"
            except subprocess.TimeoutExpired:
                pass
        process.terminate()
        try:
            process.wait(timeout=5)
            result = "exact-pid-terminate"
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            result = "exact-pid-kill"
        self._children.pop(process.pid, None)
        return result

    def stop_all_exact(self) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []
        for pid, process in list(self._children.items()):
            results.append((pid, self.stop_exact(process, graceful_break=True)))
        return results


def controlled_environment() -> dict[str, str]:
    result = {name: os.environ[name] for name in ENV_ALLOWLIST if name in os.environ}
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def load_startup_configuration() -> dict[str, object]:
    global PYTHON_EXE, HOST, PORT, RESERVED_PORT
    config = load_config(require_local_files=True)
    PYTHON_EXE = Path(str(config["python_executable"]))
    HOST = str(config["host"])
    PORT = int(config["broker_port"])
    RESERVED_PORT = int(config["reserved_port"])
    return config


def create_browser_profile() -> Path:
    # Retained until independent post-test ownership/inventory verification.
    return Path(tempfile.mkdtemp(prefix="maeve-close-owned-edge-")).resolve(strict=True)


def browser_arguments(profile: Path, local_url: str, *, test_mode: str | None = None) -> list[str]:
    if test_mode not in (None, "no-voice"):
        raise RuntimeError("Invalid explicit test mode")
    if not profile.is_absolute() or not profile.name.startswith("maeve-close-owned-edge-"):
        raise RuntimeError("Dedicated browser profile identity rejected")
    if not local_url.startswith(f"http://{HOST}:{PORT}/"):
        raise RuntimeError("Nonlocal browser destination rejected")
    arguments = [str(EDGE_EXE), f"--user-data-dir={profile}", f"--app={local_url}",
                 "--no-first-run", "--no-default-browser-check", "--disable-background-mode"]
    if test_mode == "no-voice":
        arguments += ["--disable-background-networking",
            "--disable-sync", "--disable-extensions", "--disable-component-update",
            "--disable-domain-reliability", "--disable-breakpad", "--disable-crash-reporter",
            "--disable-default-apps", "--disable-client-side-phishing-detection",
            "--disable-features=PreconnectToSearch,Prerender2,SpeculationRulesPrefetch,msEdgeSidebarV2,msStartupBoost",
            "--no-pings", "--metrics-recording-only", "--deny-permission-prompts", "--mute-audio",
                      "--autoplay-policy=user-gesture-required",
                      "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=127.0.0.1"]
    return arguments


def ensure_closed(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex((HOST, port)) == 0:
            raise RuntimeError(f"Required closed port is active: {HOST}:{port}")


def verify_files() -> None:
    missing = [str(path) for path in REQUIRED_FILES if not path.is_file()]
    if missing:
        raise RuntimeError("Required runtime files are missing: " + ", ".join(missing))
    if not PYTHON_EXE.is_file() or not WSL_EXE.is_file():
        raise RuntimeError("The exact verified Python or WSL executable is missing")


def verify_python_runtime() -> None:
    """Reject PATH aliases and unrelated project virtual environments."""
    try:
        actual = Path(sys.executable).resolve(strict=True)
        approved = PYTHON_EXE.resolve(strict=True)
    except OSError as error:
        raise RuntimeError("The verified Maeve Python runtime could not be resolved") from error
    if actual != approved or sys.version_info[:2] < (3, 11):
        raise RuntimeError(
            "Unapproved Python runtime. Double-click START MAEVE.cmd; do not use "
            "python, py, or another project virtual environment"
        )


def verify_wsl_stopped(children: OwnedChildren, env: dict[str, str]) -> None:
    process = children.start(
        [str(WSL_EXE), "--list", "--verbose"], cwd=RUNTIME_ROOT, env=env, capture=True
    )
    stdout, _stderr = process.communicate(timeout=15)
    children.forget_if_exited(process)
    if process.returncode != 0:
        raise RuntimeError("WSL stopped-state query failed")
    text = stdout.decode("utf-16", errors="replace").replace("\x00", "")
    running = [line.strip() for line in text.splitlines() if "Maeve-" in line and "Running" in line]
    if running:
        raise RuntimeError("A Maeve WSL distribution is running")


def _validated_health(body: bytes) -> dict[str, object]:
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Maeve readiness response was malformed") from error
    if not isinstance(result, dict):
        raise RuntimeError("Maeve readiness response was malformed")
    required = {"broker": "READY", "sttState": "READY", "sttSubmissionCount": 0,
                "reasoningRequests": 0, "runMode": "CONTROLLED_CONVERSATION"}
    if any(result.get(key) != value for key, value in required.items()):
        raise RuntimeError("Maeve readiness response did not match the authenticated startup contract")
    return result


def _safe_exited_output(broker: subprocess.Popen[bytes], token: str) -> str:
    try:
        stdout, stderr = broker.communicate(timeout=1)
    except (subprocess.TimeoutExpired, OSError):
        return "captured-output-unavailable"
    combined = (stdout or b"") + b"\n" + (stderr or b"")
    text = combined.decode("utf-8", errors="replace").replace(token, "[REDACTED]")
    text = " | ".join(line.strip() for line in text.splitlines() if line.strip())
    return text[:1000] or "captured-output-empty"


def wait_for_health(token: str, broker: subprocess.Popen[bytes]) -> dict[str, object]:
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    request = urllib.request.Request(
        f"http://{HOST}:{PORT}/health", headers={"X-Maeve-Token": token}
    )
    connection_failures = 0
    while time.monotonic() < deadline:
        exit_code = broker.poll()
        if exit_code is not None:
            evidence = _safe_exited_output(broker, token)
            raise RuntimeError(
                f"Maeve broker exited before readiness with code {exit_code}; {evidence}"
            )
        try:
            with urllib.request.urlopen(request, timeout=1) as response:
                if response.status != 200:
                    raise RuntimeError(f"Maeve readiness returned HTTP {response.status}")
                return _validated_health(response.read())
        except urllib.error.HTTPError as error:
            category = "authentication rejected" if error.code == 404 else f"HTTP {error.code}"
            raise RuntimeError(f"Maeve authenticated readiness failed: {category}") from error
        except urllib.error.URLError:
            connection_failures += 1
        except (TimeoutError, ConnectionError, OSError):
            connection_failures += 1
        time.sleep(READINESS_POLL_INTERVAL_SECONDS)
    raise RuntimeError(
        "Maeve authenticated readiness timed out after "
        f"{STARTUP_DEADLINE_SECONDS:.0f}s; connection_failures={connection_failures}"
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Maeve V2 Stage 13 without a shell wrapper", allow_abbrev=False)
    class ExplicitTestMode(argparse.Action):
        def __call__(self, parser, namespace, values, option_string=None):
            if getattr(namespace, self.dest, None) is not None:
                parser.error("Repeated test-mode selection rejected")
            setattr(namespace, self.dest, values)
    parser.add_argument("--test-mode", choices=("no-voice",), default=None, action=ExplicitTestMode,
                        help="explicit no-voice validation only; never enabled by the normal CMD entry point")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke-test", action="store_true", help="health-check and stop without a browser")
    mode.add_argument("--open-browser", action="store_true", help="open the approved local Edge UI")
    parser.add_argument("--voice-provider", choices=("elevenlabs", "qwen"), default="elevenlabs",
                        help="explicit provider; Qwen is never selected automatically")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    print("MAEVE_LAUNCH_MODE=" + ("TEST_NO_VOICE" if args.test_mode else "NORMAL_OPERATOR"), flush=True)
    children = OwnedChildren()
    token: str | None = None
    broker: subprocess.Popen[bytes] | None = None
    browser: subprocess.Popen[bytes] | None = None
    shutdown_method = "not-started"
    try:
        config = load_startup_configuration()
        verify_python_runtime()
        verify_files()
        ensure_closed(PORT)
        ensure_closed(RESERVED_PORT)
        base_env = controlled_environment()
        verify_wsl_stopped(children, base_env)
        token = secrets.token_hex(32)
        broker_env = dict(base_env)
        broker_env.update(export_environment(config))
        broker_env[TOKEN_ENV] = token
        broker = children.start(
            [str(PYTHON_EXE), "-B", str(SERVER), "--port", str(PORT), "--controlled-conversation", "--voice-provider", args.voice_provider],
            cwd=SERVER.parent, env=broker_env, capture=True,
            process_group=True,
        )
        health = wait_for_health(token, broker)
        ensure_closed(RESERVED_PORT)
        print(
            "MAEVE_LAUNCHER_READY "
            f"broker_pid={broker.pid} listener={HOST}:{PORT} port_48178=closed "
            f"mode={health.get('runMode', 'unknown')}",
            flush=True,
        )
        if args.smoke_test:
            print("MAEVE_SMOKE_TEST=PASS browser=0 microphone=0 conversation=0", flush=True)
            return 0
        if args.open_browser:
            if not EDGE_EXE.is_file():
                raise RuntimeError("The exact Microsoft Edge executable is missing")
            local_url = f"http://{HOST}:{PORT}/?ptt=physical-test#token={token}"
            browser_profile = create_browser_profile()
            print("MAEVE_OWNED_BROWSER_PROFILE=DEDICATED", flush=True)
            browser = children.start(
                browser_arguments(browser_profile, local_url, test_mode=args.test_mode),
                cwd=EDGE_EXE.parent,
                env=base_env,
            )
            print(f"MAEVE_BROWSER_CHILD_STARTED pid={browser.pid} token=private", flush=True)
        print("Press Ctrl+C to stop only launcher-owned child processes.", flush=True)
        while broker.poll() is None:
            time.sleep(0.25)
        return broker.returncode or 0
    except KeyboardInterrupt:
        print("MAEVE_LAUNCHER_STOP requested", flush=True)
        return 0
    except Exception as error:
        print(f"MAEVE_LAUNCHER_ERROR {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        token = None
        if broker is not None:
            shutdown_method = children.stop_exact(broker, graceful_break=True)
        if browser is not None:
            # Give the confirmed in-app close time to exit its dedicated instance.
            try:
                browser.wait(timeout=15)
            except subprocess.TimeoutExpired:
                print("MAEVE_BROWSER_GRACEFUL_EXIT_FAILED owned fallback required", flush=True)
        other_results = children.stop_all_exact()
        ensure_closed(PORT)
        ensure_closed(RESERVED_PORT)
        print(
            f"MAEVE_LAUNCHER_STOPPED broker={shutdown_method} other_children={len(other_results)} "
            "ports=closed token=cleared",
            flush=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
