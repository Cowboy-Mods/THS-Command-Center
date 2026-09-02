#!/usr/bin/env python3
"""Text-only official Codex subscription gateway. JSONL stdin/stdout; no prompt persistence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

RUNTIME_VERSION = "0.5.0-stage13"
MODEL = "gpt-5.6-sol"
MAX_PROMPT_CHARS = 14_000
MAX_RESPONSE_CHARS = 360
TIMEOUT_SECONDS = 90
CODEX = Path(os.environ.get("MAEVE_CODEX_EXECUTABLE", "UNCONFIGURED_CODEX_EXECUTABLE"))
DISABLED_FEATURES = (
    "shell_tool", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
    "computer_use", "apps", "plugins", "skill_search", "multi_agent", "multi_agent_v2",
    "enable_mcp_apps", "remote_plugin", "image_generation", "in_app_browser",
    "unified_exec", "code_mode_host", "view_image", "workspace_dependencies", "tool_suggest",
    "standalone_web_search", "web_search_cached", "web_search_request", "in_app_chat",
)
TOOL_MARKERS = ("tool", "command", "shell", "browser", "computer", "mcp", "plugin", "agent", "function_call")
SAFE_LIFECYCLE_EVENTS = {"thread.started", "turn.started", "turn.completed", "item.started", "item.completed", "error"}
SAFE_ITEM_TYPES = {"agent_message", "reasoning", "error"}
DIAGNOSTIC_FIELDS = ("text", "tool", "action", "error", "usage", "metadata")


class ProhibitedCodexEvent(RuntimeError):
    """Carries only a content-free event classification safe for certification evidence."""

    def __init__(self, descriptor: dict[str, object]) -> None:
        self.descriptor = descriptor
        super().__init__("Codex emitted a prohibited event: " + json.dumps(descriptor, sort_keys=True, separators=(",", ":")))


def send(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")), flush=True)


def event_text(event: dict[str, object]) -> str | None:
    if event.get("type") == "item.completed":
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            return item["text"]
    if event.get("type") in {"response.completed", "turn.completed"}:
        value = event.get("response") or event.get("turn")
        if isinstance(value, dict) and isinstance(value.get("output_text"), str):
            return value["output_text"]
    return None


def _field_exists(value: object, field: str) -> bool:
    if isinstance(value, dict):
        return field in value or any(_field_exists(child, field) for child in value.values())
    if isinstance(value, list):
        return any(_field_exists(child, field) for child in value)
    return False


def describe_event(event: dict[str, object]) -> dict[str, object]:
    event_type = str(event.get("type", "")).casefold()
    item = event.get("item")
    item_type = str(item.get("type", "")).casefold() if isinstance(item, dict) else ""
    marker_shaped = any(marker in event_type for marker in TOOL_MARKERS) or (
        item_type not in SAFE_ITEM_TYPES and any(marker in item_type for marker in TOOL_MARKERS)
    )
    action_field = _field_exists(event, "tool") or _field_exists(event, "action")
    if marker_shaped or action_field:
        classification = "genuine-tool-or-action"
    elif event_type == "error" or item_type == "error":
        classification = "error"
    elif item_type == "agent_message":
        classification = "assistant-text"
    elif item_type == "reasoning":
        classification = "reasoning"
    elif event_type in SAFE_LIFECYCLE_EVENTS and not item_type:
        classification = "lifecycle"
    else:
        classification = "unknown"
    descriptor: dict[str, object] = {
        "eventType": event_type,
        "itemType": item_type,
        "classification": classification,
    }
    for field in DIAGNOSTIC_FIELDS:
        descriptor[f"has{field.title()}Field"] = _field_exists(event, field)
    return descriptor


def is_prohibited_event(event: dict[str, object]) -> bool:
    descriptor = describe_event(event)
    event_type = str(descriptor["eventType"])
    item_type = str(descriptor["itemType"])
    if descriptor["classification"] == "genuine-tool-or-action":
        return True
    if event_type not in SAFE_LIFECYCLE_EVENTS:
        return True
    if item_type and item_type not in SAFE_ITEM_TYPES:
        return True
    return False


def run_request(prompt: str) -> dict[str, object]:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError("prompt outside bounded text-only policy")
    if not CODEX.is_file():
        raise RuntimeError("verified Codex executable is missing")
    work = Path(tempfile.mkdtemp(prefix="maeve-reasoning-"))
    command = [str(CODEX), "exec", "-", "--model", MODEL, "--sandbox", "read-only", "--ephemeral",
               "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--strict-config",
               "--json", "--color", "never", "--cd", str(work)]
    for feature in DISABLED_FEATURES:
        command.extend(("--disable", feature))
    process: subprocess.Popen[str] | None = None
    timer: threading.Timer | None = None
    events = 0
    final_text: str | None = None
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", bufsize=1,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=os.environ.copy())
        timer = threading.Timer(TIMEOUT_SECONDS, lambda: process.kill() if process and process.poll() is None else None)
        timer.daemon = True; timer.start()
        assert process.stdin and process.stdout
        process.stdin.write(prompt); process.stdin.close()
        for line in process.stdout:
            try: event = json.loads(line)
            except json.JSONDecodeError: continue
            if not isinstance(event, dict): continue
            events += 1
            if is_prohibited_event(event):
                descriptor = describe_event(event)
                process.kill(); raise ProhibitedCodexEvent(descriptor)
            candidate = event_text(event)
            if candidate is not None: final_text = candidate
        stderr = process.stderr.read() if process.stderr else ""
        code = process.wait(timeout=5)
        if code != 0:
            raise RuntimeError("Codex reasoning request failed or timed out")
        if not final_text or len(final_text) > MAX_RESPONSE_CHARS:
            raise RuntimeError("Codex returned no bounded assistant text")
        return {"type": "response", "runtimeVersion": RUNTIME_VERSION, "model": MODEL,
                "text": " ".join(final_text.split()), "toolEvents": 0, "eventCount": events,
                "durationSeconds": time.monotonic() - started, "workingDirectoryEmpty": not any(work.iterdir()),
                "stderrPresent": bool(stderr.strip())}
    finally:
        if timer: timer.cancel()
        if process and process.poll() is None: process.kill(); process.wait(timeout=5)
        shutil.rmtree(work, ignore_errors=False)


def main() -> None:
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("type") == "shutdown": break
        if request.get("type") != "reason" or set(request) != {"type", "prompt", "runtimeVersion"} or request.get("runtimeVersion") != RUNTIME_VERSION:
            send({"type": "error", "error": "invalid request"}); continue
        try: send(run_request(request["prompt"]))
        except Exception as exc: send({"type": "error", "error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    main()
