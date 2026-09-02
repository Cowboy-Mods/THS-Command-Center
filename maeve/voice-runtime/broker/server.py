#!/usr/bin/env python3
"""Maeve V2 Stage 9 loopback-only typed-voice runtime broker."""
from __future__ import annotations

import argparse, atexit, base64, hashlib, hmac, json, mimetypes, os, posixpath, queue, re, secrets, subprocess, sys, threading, time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

RUNTIME_ID = "maeve-v2-live"
RUNTIME_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RUNTIME_ROOT))
from runtime_config import export_environment, load_config  # noqa: E402
from conversation_policy import (ConversationSession, MAX_RESPONSE_CHARS, RUNTIME_VERSION,
                                 SESSION_WARNING_55_PROMPT, SESSION_WARNING_59_PROMPT,
                                 STILL_THERE_PROMPT, TIMEOUT_POLICY, build_prompt,
                                 classify_local_intent, clean_text, validate_response)
from model_scheduler import ModelScheduler
from voice_provider import ElevenLabsProvider, MockElevenLabsProvider, ProviderFailure, UsageLedger, UsageLimits
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 48177
MAX_REQUEST_TARGET = 2048
MAX_JSON_BODY = 32768
MAX_AUDIO_BYTES = 4 * 1024 * 1024
TOKEN_HEADER = "X-Maeve-Token"
TOKEN_ENV = "MAEVE_RUNTIME_TOKEN"
TOKEN_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
SESSION_PATTERN = re.compile(r"^[a-f0-9]{32}$")
CONVERSATION_TOKEN_HEADER = "X-Maeve-Conversation-Token"
CONVERSATION_SESSION_HEADER = "X-Maeve-Conversation-Session"
CONVERSATION_TURN_HEADER = "X-Maeve-Conversation-Turn"
EXPECTED_ORIGIN = f"http://{LOOPBACK_HOST}:{DEFAULT_PORT}"
APPROVED_ENDPOINT_HEADER = "UNCONFIGURED"
APPROVED_ENDPOINT_SELECTOR = "UNCONFIGURED"
ALLOWED_AUDIO_TYPES = frozenset({"audio/webm", "audio/webm;codecs=opus", "audio/ogg;codecs=opus"})
QWEN_FAILURE_CATEGORIES = frozenset({"QWEN_START_FAILED", "QWEN_TIMEOUT", "QWEN_WORKER_FAILED",
                                      "QWEN_PROTOCOL_MISSING", "QWEN_PROTOCOL_INVALID_JSON",
                                      "QWEN_PROTOCOL_NON_OBJECT", "QWEN_PROTOCOL_SCHEMA_FAILED",
                                      "QWEN_PROTOCOL_FAILED", "QWEN_EVIDENCE_FAILED", "QWEN_AUDIO_FAILED",
                                      "QWEN_FAILED"})
TURN_FAILURE_CATEGORIES = frozenset({"STT_START_FAILED", "STT_TIMEOUT", "STT_WORKER_FAILED", "STT_PROTOCOL_FAILED",
                                     "STT_EVIDENCE_FAILED", "STT_EMPTY_TRANSCRIPT", "STT_FAILED", "INTENT_FAILED",
                                     "REASONER_START_FAILED", "REASONER_RESPONSE_FAILED", "RESPONSE_IDENTITY_FAILED",
                                     "VOICE_GENERATION_FAILED", *QWEN_FAILURE_CATEGORIES, "PLAYBACK_PREP_FAILED"})
GENERIC_TURN_FAILURE = "TURN_FAILED"
REVIEW_FAILURES = {
    "REVIEW_APPROVAL_FAILED": "Transcript approval failed; no automatic retry",
    "REASONING_FAILED": "Reasoning failed; no automatic retry",
    "VOICE_GENERATION_FAILED": "Voice generation failed; no automatic retry",
    "AUDIO_RESPONSE_INVALID": "Audio response invalid; no automatic retry",
    "RESPONSE_PACKAGING_FAILED": "Playback preparation failed; no automatic retry",
}
QWEN_READY_TIMEOUT_SECONDS = 300
QWEN_GENERATION_TIMEOUT_SECONDS = 300
RUN_MODE = "STOPPED"
APPROVED_TEXT = "Maeve’s live voice and visual systems are operating together."
UI_ROOT = (Path(__file__).resolve().parent.parent / "ui").resolve()
WINDOWS_AUDIO: Path | None = None
RUNTIME_CONFIG: dict[str, object] | None = None
STAGE9_AUDIO_SHA256 = "c5b3b82b2d757153e7d860bb372e9a3db1d5fa4102577ee387afedc9b006e519"
STAGE9_AUDIO_BYTES = 284204
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "font-src 'none'; media-src 'self' blob:; object-src 'none'; frame-src 'none'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'none'; worker-src 'none'")

def allowed_files() -> dict[str, Path]:
    files = {f"/{p.relative_to(UI_ROOT).as_posix()}": p.resolve() for p in UI_ROOT.rglob("*") if p.is_file()}
    files["/"] = UI_ROOT / "index.html"
    return files

ALLOWED_FILES = allowed_files()
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/png", ".png")

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()

def diagnostic_audio_available() -> bool:
    return WINDOWS_AUDIO is not None and WINDOWS_AUDIO.is_file()

def configure_runtime() -> dict[str, object]:
    global RUNTIME_CONFIG, LOOPBACK_HOST, DEFAULT_PORT, EXPECTED_ORIGIN
    global APPROVED_ENDPOINT_HEADER, APPROVED_ENDPOINT_SELECTOR, WINDOWS_AUDIO
    config = load_config(require_local_files=True)
    LOOPBACK_HOST = str(config["host"])
    DEFAULT_PORT = int(config["broker_port"])
    EXPECTED_ORIGIN = f"http://{LOOPBACK_HOST}:{DEFAULT_PORT}"
    APPROVED_ENDPOINT_HEADER = str(config["approved_label"])
    APPROVED_ENDPOINT_SELECTOR = str(config["approved_selector"])
    WINDOWS_AUDIO = Path(str(config["diagnostic_wav"])) if config["diagnostic_wav"] else None
    os.environ.update(export_environment(config))
    RUNTIME_CONFIG = config
    return config

class TurnStageFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        if category not in TURN_FAILURE_CATEGORIES: raise ValueError("unknown bounded turn failure category")
        self.category = category
        super().__init__("bounded controlled-conversation stage failure")

class QwenStageFailure(RuntimeError):
    def __init__(self, category: str) -> None:
        if category not in QWEN_FAILURE_CATEGORIES: raise ValueError("unknown bounded Qwen failure category")
        self.category = category
        super().__init__("bounded local voice stage failure")

def turn_failure_payload(error: BaseException) -> bytes:
    category = error.category if isinstance(error, TurnStageFailure) and error.category in TURN_FAILURE_CATEGORIES else GENERIC_TURN_FAILURE
    return json.dumps({"error":"Controlled conversation turn failed; no automatic retry","failureCategory":category}, separators=(",", ":")).encode()

def review_failure_payload(category: str) -> bytes:
    safe_category = category if category in REVIEW_FAILURES else "RESPONSE_PACKAGING_FAILED"
    return json.dumps({"error": REVIEW_FAILURES[safe_category], "failureCategory": safe_category},
                      separators=(",", ":")).encode()

class VoiceWorker:
    """One local WSL worker over process stdin/stdout; no WSL listener."""
    def __init__(self, selected_provider: str = "ELEVENLABS") -> None:
        self.state, self.detail = "LOADING", "CANONICAL VOICE LOADING"
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.generation_consumed = False
        self.ready_evidence = None
        self.generation_evidence = None
        self.browser_evidence = None
        self.response_audio: bytes | None = None
        self.response_audio_served = False
        self.response_count = 0
        self.playback_completed = False
        self.active_response_id: str | None = None
        self.last_cancelled_response_id: str | None = None
        self.error = None
        self.failure_category: str | None = None
        self.qwen_start_count = 0
        if selected_provider not in {"ELEVENLABS", "QWEN"}: raise ValueError("Explicit voice provider required")
        self.selected_provider = selected_provider
        self.cloud = ElevenLabsProvider()

    def health(self) -> dict[str, object]:
        provider = self.cloud.status() if self.selected_provider == "ELEVENLABS" else {
            "provider":"QWEN", "voice":"Candidate B", "model":"LOCAL_QWEN", "available":self.state not in {"UNAVAILABLE","ERROR"},
            "display":"LOCAL VOICE — QWEN", "usage":None}
        truthful_state = self.state if provider["available"] else "UNAVAILABLE"
        return {"runtime": RUNTIME_ID, "version": RUNTIME_VERSION, "broker": "READY", "voiceState": truthful_state,
                "provider": provider["provider"], "voiceProvider": provider,
            "microphone": "PTT_ONLY_CLOSED", "networkProvider": "OPENAI_CODEX_ONLY", "localModelNetwork": "BLOCKED", "generationConsumed": self.generation_consumed,
            "audioReady": bool(self.generation_evidence and diagnostic_audio_available()), "runMode": RUN_MODE,
            "gpuOwner": GPU.owner if "GPU" in globals() else "NONE", "responseCount": self.response_count,
            "qwenStartCount": self.qwen_start_count,
            "qwenReadyRequired": self.selected_provider == "QWEN",
            "responseAudioInMemory": self.response_audio is not None, "responseAudioServed": self.response_audio_served,
            "responsePlaybackCompleted": self.playback_completed}

    def resume_validated_audio(self) -> None:
        if self.selected_provider == "ELEVENLABS":
            self.generation_consumed = True
            self.generation_evidence = None
            self.state, self.detail = ("IDLE", "CLOUD VOICE READY") if self.cloud.available() else ("UNAVAILABLE", "ELEVENLABS UNAVAILABLE — LOCAL FALLBACK REQUIRES APPROVAL")
            return
        if not diagnostic_audio_available() or WINDOWS_AUDIO is None or WINDOWS_AUDIO.stat().st_size != STAGE9_AUDIO_BYTES or sha256_file(WINDOWS_AUDIO) != STAGE9_AUDIO_SHA256:
            raise RuntimeError("Stage 9 validated WAV recovery gate failed")
        self.generation_consumed = True
        self.generation_evidence = {"type": "generated", "status": "PASS", "attempt": 1, "recoveredForPlaybackOnly": True,
                                    "audio": {"bytes": STAGE9_AUDIO_BYTES, "sha256": STAGE9_AUDIO_SHA256, "sampleRate": 24000,
                                              "channels": 1, "frames": 142080, "durationSeconds": 5.92, "format": "RIFF/WAVE PCM-16"}}
        self.state, self.detail = "IDLE", "VALIDATED STAGE 9 AUDIO READY"

    def start(self) -> None:
        threading.Thread(target=self._start_worker, name="maeve-qwen-worker-start", daemon=True).start()

    def start_for_response(self) -> None:
        if self.process and self.process.poll() is None: return
        self._start_worker()
        if self.state != "IDLE" or not self.process: raise QwenStageFailure(self.failure_category or "QWEN_START_FAILED")

    def _stderr_pump(self) -> None:
        assert self.process and self.process.stderr
        for _line in self.process.stderr: pass

    def _read_json(self, timeout_seconds: float) -> dict[str, object]:
        process = self.process
        if not process or not process.stdout: raise QwenStageFailure("QWEN_START_FAILED")
        result: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)
        def read_one() -> None:
            try:
                line = process.stdout.readline()
                if not line:
                    code = process.poll()
                    result.put(("worker" if code not in {None, 0} else "missing", None))
                    return
                try: value = json.loads(line)
                except json.JSONDecodeError:
                    result.put(("invalid-json", None)); return
                result.put(("value", value) if isinstance(value, dict) else ("non-object", None))
            except Exception:
                result.put(("protocol-unknown", None))
        threading.Thread(target=read_one, name="maeve-qwen-worker-stdout", daemon=True).start()
        try: kind, value = result.get(timeout=timeout_seconds)
        except queue.Empty: raise QwenStageFailure("QWEN_TIMEOUT") from None
        if kind == "worker": raise QwenStageFailure("QWEN_WORKER_FAILED")
        if kind == "missing": raise QwenStageFailure("QWEN_PROTOCOL_MISSING")
        if kind == "invalid-json": raise QwenStageFailure("QWEN_PROTOCOL_INVALID_JSON")
        if kind == "non-object": raise QwenStageFailure("QWEN_PROTOCOL_NON_OBJECT")
        if kind == "protocol-unknown": raise QwenStageFailure("QWEN_PROTOCOL_FAILED")
        if kind != "value" or not isinstance(value, dict): raise QwenStageFailure("QWEN_FAILED")
        return value

    def _start_worker(self) -> None:
        self.qwen_start_count += 1
        qwen = RUNTIME_CONFIG["qwen"] if RUNTIME_CONFIG else {}
        if not isinstance(qwen, dict) or not all(qwen.get(key) for key in ("distribution", "python", "worker_path", "model_path", "voice_identity_path")):
            raise QwenStageFailure("QWEN_START_FAILED")
        command = ["wsl.exe", "-d", str(qwen["distribution"]), "-u", "root", "--", "unshare", "--net", "--", "env",
                   "CUBLAS_WORKSPACE_CONFIG=:4096:8", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1", "HF_DATASETS_OFFLINE=1",
                   "HF_HUB_DISABLE_TELEMETRY=1", "DO_NOT_TRACK=1", "TOKENIZERS_PARALLELISM=false", "PYTHONNOUSERSITE=1",
                   "PYTHONDONTWRITEBYTECODE=1", "PIP_NO_INDEX=1",
                   f"MAEVE_QWEN_MODEL_PATH={qwen['model_path']}", f"MAEVE_QWEN_IDENTITY_PATH={qwen['voice_identity_path']}",
                   str(qwen["python"]), str(qwen["worker_path"])]
        acquired = False
        try:
            acquired = GPU.acquire("QWEN")
            if not acquired: raise QwenStageFailure("QWEN_START_FAILED")
            try:
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                text=True, encoding="utf-8", errors="replace", bufsize=1,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError: raise QwenStageFailure("QWEN_START_FAILED") from None
            threading.Thread(target=self._stderr_pump, name="maeve-qwen-worker-stderr", daemon=True).start()
            response = self._read_json(QWEN_READY_TIMEOUT_SECONDS)
            if response.get("type") == "error": raise QwenStageFailure("QWEN_WORKER_FAILED")
            if not isinstance(response.get("type"), str) or not isinstance(response.get("runtimeVersion"), str):
                raise QwenStageFailure("QWEN_PROTOCOL_SCHEMA_FAILED")
            if response.get("type") != "ready" or response.get("runtimeVersion") != RUNTIME_VERSION:
                raise QwenStageFailure("QWEN_EVIDENCE_FAILED")
            self.ready_evidence = response
            self.failure_category = None
            self.state, self.detail = "IDLE", "CANONICAL MAEVE VOICE READY"
        except QwenStageFailure as failure:
            self.failure_category = failure.category
            self.error = failure.category
            self.state, self.detail = "UNAVAILABLE", "CANONICAL VOICE UNAVAILABLE"
            self.stop()
        except Exception:
            self.failure_category = "QWEN_FAILED"
            self.error = "QWEN_FAILED"
            self.state, self.detail = "UNAVAILABLE", "CANONICAL VOICE UNAVAILABLE"
            self.stop()

    def generate(self, text: str) -> dict[str, object]:
        with self.lock:
            if self.generation_consumed: raise RuntimeError("Stage 9 generation already consumed")
            if self.state != "IDLE" or not self.process or not self.process.stdin: raise RuntimeError("Canonical Maeve voice unavailable")
            self.generation_consumed = True
            self.state, self.detail = "GENERATING", "ONE AUTHORIZED GENERATION ACTIVE"
            self.process.stdin.write(json.dumps({"type": "generate", "text": text}, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            try:
                response = self._read_json()
                if response.get("type") != "generated" or response.get("status") != "PASS":
                    raise RuntimeError(str(response.get("error") or "Worker generation failed"))
                if not diagnostic_audio_available() or WINDOWS_AUDIO is None: raise RuntimeError("Validated Stage 9 WAV is missing")
                audio = response.get("audio")
                if not isinstance(audio, dict) or audio.get("sha256") != sha256_file(WINDOWS_AUDIO) or audio.get("bytes") != WINDOWS_AUDIO.stat().st_size:
                    raise RuntimeError("Windows WAV evidence mismatch")
                self.generation_evidence = response
                self.state, self.detail = "IDLE", "GENERATION COMPLETE · PLAYBACK READY"
                return response
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                self.state, self.detail = "ERROR", "NO SPEECH OUTPUT"
                raise

    def generate_response(self, text: str, *, response_id: str | None = None, response_limit: int = 2, require_stt: bool = True) -> dict[str, object]:
        if self.selected_provider == "ELEVENLABS":
            try:
                if self.response_count >= response_limit: raise QwenStageFailure("QWEN_FAILED")
                if require_stt and STT.state != "COMPLETED": raise QwenStageFailure("QWEN_START_FAILED")
                result = self.cloud.generate_response(validate_response(text), str(response_id or ""))
                self.response_count += 1
                self.active_response_id = response_id
                self.response_audio = b"cloud-owned"
                self.response_audio_served = False
                self.generation_evidence = result
                self.state, self.detail = "READY_FOR_PLAYBACK", "ELEVENLABS RESPONSE READY IN MEMORY"
                return result
            except ProviderFailure:
                self.state, self.detail = "ERROR", "ELEVENLABS RESPONSE FAILED — NO FALLBACK"
                raise
        with self.lock:
            try:
                text = validate_response(text)
                if self.response_count >= response_limit: raise QwenStageFailure("QWEN_FAILED")
                if (require_stt and STT.state != "COMPLETED") or GPU.owner != "NONE": raise QwenStageFailure("QWEN_START_FAILED")
                self.response_count += 1
                self.start_for_response()
                if self.state != "IDLE": raise QwenStageFailure(self.failure_category or "QWEN_START_FAILED")
                if GPU.owner != "QWEN" or not self.process or not self.process.stdin: raise QwenStageFailure("QWEN_START_FAILED")
                self.state, self.detail = "GENERATING", "ONE APPROVED CONTROLLED RESPONSE"
                try:
                    self.process.stdin.write(json.dumps({"type": "generate", "text": text}, ensure_ascii=False) + "\n")
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError): raise QwenStageFailure("QWEN_WORKER_FAILED") from None
                response = self._read_json(QWEN_GENERATION_TIMEOUT_SECONDS)
                if response.get("type") == "error": raise QwenStageFailure("QWEN_WORKER_FAILED")
                if (not isinstance(response.get("type"), str) or not isinstance(response.get("status"), str)
                        or not isinstance(response.get("text"), str) or not isinstance(response.get("audioBase64"), str)
                        or not isinstance(response.get("audio"), dict)):
                    raise QwenStageFailure("QWEN_PROTOCOL_SCHEMA_FAILED")
                if response.get("type") != "generated" or response.get("status") != "PASS" or response.get("text") != text:
                    raise QwenStageFailure("QWEN_EVIDENCE_FAILED")
                encoded = response.pop("audioBase64", None)
                audio = response.get("audio")
                try: decoded = base64.b64decode(encoded, validate=True)
                except Exception: raise QwenStageFailure("QWEN_AUDIO_FAILED") from None
                if len(decoded) != audio.get("bytes") or hashlib.sha256(decoded).hexdigest() != audio.get("sha256"):
                    raise QwenStageFailure("QWEN_AUDIO_FAILED")
                self.response_audio = decoded
                self.response_audio_served = False
                self.generation_evidence = response
                self.failure_category = None
                self.state, self.detail = "READY_FOR_PLAYBACK", "CONTROLLED RESPONSE READY IN MEMORY"
                return response
            except QwenStageFailure as failure:
                self.failure_category = failure.category
                self.error = failure.category
                self.state, self.detail = "ERROR", "CONTROLLED RESPONSE FAILED"
                self.stop()
                raise
            except Exception:
                self.failure_category = "QWEN_FAILED"
                self.error = "QWEN_FAILED"
                self.state, self.detail = "ERROR", "CONTROLLED RESPONSE FAILED"
                self.stop()
                raise QwenStageFailure("QWEN_FAILED") from None

    def bind_response(self, response_id: str) -> None:
        with self.lock:
            if self.selected_provider == "ELEVENLABS":
                if self.active_response_id != response_id: raise RuntimeError("Cloud response binding gate failed")
                return
            if self.active_response_id is not None or self.response_audio is None: raise RuntimeError("Controlled response binding gate failed")
            self.active_response_id = response_id

    def take_response_audio(self, response_id: str | None) -> bytes:
        with self.lock:
            if self.selected_provider == "ELEVENLABS":
                audio = self.cloud.take_audio(str(response_id))
                self.response_audio_served = True
                return audio
            if self.active_response_id is not None and response_id != self.active_response_id: raise RuntimeError("Controlled response identity rejected")
            if self.response_audio is None or self.response_audio_served: raise RuntimeError("Controlled response audio unavailable")
            self.response_audio_served = True
            return self.response_audio

    def complete_response_playback(self, response_id: str | None) -> None:
        with self.lock:
            if self.selected_provider == "ELEVENLABS":
                self.cloud.complete(str(response_id))
                self.response_audio = None; self.response_audio_served = False; self.playback_completed = True
                self.active_response_id = None; self.state, self.detail = "IDLE", "CLOUD RESPONSE COMPLETE · AUDIO RELEASED"
                return
            if self.active_response_id is not None and response_id != self.active_response_id: raise RuntimeError("Controlled response completion identity rejected")
            if self.response_count < 1 or self.response_audio is None or not self.response_audio_served: raise RuntimeError("No controlled response is awaiting completion")
            self.response_audio = None
            self.playback_completed = True
            self.stop()
            self.active_response_id = None
            self.state, self.detail = "IDLE", "CONTROLLED RESPONSE COMPLETE · AUDIO RELEASED"

    def cancel_response(self, response_id: str) -> str:
        with self.lock:
            if self.selected_provider == "ELEVENLABS":
                status = self.cloud.cancel(response_id)
                self.response_audio = None; self.response_audio_served = False; self.active_response_id = None
                self.last_cancelled_response_id = response_id
                self.state, self.detail = "IDLE", "CLOUD RESPONSE CANCELLED · AUDIO RELEASED"
                return status
            if response_id == self.last_cancelled_response_id: return "ALREADY_CANCELLED"
            if self.active_response_id is None: return "NO_ACTIVE_RESPONSE"
            if response_id != self.active_response_id: raise RuntimeError("Response cancellation identity rejected")
            self.response_audio = None
            self.response_audio_served = False
            self.playback_completed = False
            self.stop()
            self.active_response_id = None
            self.last_cancelled_response_id = response_id
            self.state, self.detail = "IDLE", "CONTROLLED RESPONSE CANCELLED · AUDIO RELEASED"
            return "CANCELLED"

    def stop(self) -> None:
        self.cloud.stop()
        process = self.process
        try:
            if process and process.poll() is None:
                try:
                    if process.stdin:
                        process.stdin.write('{"type":"shutdown"}\n'); process.stdin.flush()
                    process.wait(timeout=12)
                except Exception:
                    process.terminate()
                    try: process.wait(timeout=8)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        finally:
            self.process = None
            self.response_audio = None
            self.response_audio_served = False
            self.active_response_id = None
            if "GPU" in globals(): GPU.release("QWEN")

VOICE = VoiceWorker()
atexit.register(VOICE.stop)

GPU = ModelScheduler()

def runtime_token() -> str:
    return os.environ.get(TOKEN_ENV, "")

def token_matches(value: str | None) -> bool:
    expected = runtime_token()
    return bool(TOKEN_PATTERN.fullmatch(expected) and value and hmac.compare_digest(value, expected))

def valid_origin(value: str | None) -> bool:
    return value == EXPECTED_ORIGIN

def validate_stt_headers(content_type: str, length: int, headers: object) -> str | None:
    getter = getattr(headers, "get")
    if content_type not in ALLOWED_AUDIO_TYPES: return "unsupported audio type"
    if length < 1 or length > MAX_AUDIO_BYTES: return "audio size rejected"
    if getter("X-Endpoint-Label") != APPROVED_ENDPOINT_HEADER: return "endpoint rejected"
    if getter("X-Exact-Device-Match") != "true" or getter("X-All-Tracks-Ended") != "true": return "capture proof rejected"
    try:
        duration = float(getter("X-Recording-Duration-Ms", "0")); closure = float(getter("X-Closure-Latency-Ms", "-1"))
    except (TypeError, ValueError): return "timing proof rejected"
    if not 0 < duration <= 15250 or closure < 0: return "timing proof rejected"
    return None

class SttService:
    def __init__(self) -> None:
        self.state = "STOPPED"
        self.submission_count = 0
        self.pending_text: str | None = None
        self.pending_id: str | None = None
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self.process: subprocess.Popen[bytes] | None = None
        self.worker_pid: int | None = None
        self.session_id = secrets.token_hex(16)
        self.next_job_id = 1
        self.active_job_id: int | None = None
        self.invalidated_jobs: set[int] = set()
        self.model_load_count = 0
        self.worker_start_count = 0

    @staticmethod
    def _command() -> list[str]:
        if not RUNTIME_CONFIG: raise TurnStageFailure("STT_START_FAILED")
        return ["wsl.exe", "-d", str(RUNTIME_CONFIG["stt_distribution"]), "-u", "root", "--", "env", "PIP_NO_INDEX=1",
                "PIP_DISABLE_PIP_VERSION_CHECK=1", "HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1",
                "HF_HUB_DISABLE_TELEMETRY=1", "PYTHONDONTWRITEBYTECODE=1", "CUDA_VISIBLE_DEVICES=0",
                "LD_LIBRARY_PATH=/opt/maeve-stt/venv/lib/python3.12/site-packages/nvidia/cublas/lib:/opt/maeve-stt/venv/lib/python3.12/site-packages/nvidia/cudnn/lib:/opt/maeve-stt/venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib",
                f"MAEVE_STT_MODEL_PATH={RUNTIME_CONFIG['stt_model_path']}",
                "unshare", "--net", "runuser", "-u", "maeve-stt", "--", str(RUNTIME_CONFIG["stt_python"]),
                str(RUNTIME_CONFIG["stt_worker_path"])]

    def _read_json(self, timeout_seconds: float = 180) -> dict[str, object]:
        process = self.process
        if not process or not process.stdout: raise TurnStageFailure("STT_START_FAILED")
        result_queue: queue.Queue[bytes] = queue.Queue(maxsize=1)
        threading.Thread(target=lambda: result_queue.put(process.stdout.readline(MAX_AUDIO_BYTES * 2)),
                         name="maeve-stt-worker-stdout", daemon=True).start()
        try: line = result_queue.get(timeout=timeout_seconds)
        except queue.Empty: raise TurnStageFailure("STT_TIMEOUT") from None
        if not line: raise TurnStageFailure("STT_WORKER_FAILED")
        try: value = json.loads(line.decode("utf-8", errors="replace"))
        except Exception: raise TurnStageFailure("STT_PROTOCOL_FAILED") from None
        if not isinstance(value, dict): raise TurnStageFailure("STT_PROTOCOL_FAILED")
        return value

    def start(self) -> None:
        with self._lock:
            if self.process is not None or self.worker_start_count: return
            self.state = "WARMING"
            try:
                self.process = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, bufsize=0,
                                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.worker_start_count = 1
            except OSError:
                self.state = "ERROR"; raise TurnStageFailure("STT_START_FAILED") from None
        try: ready = self._read_json()
        except Exception:
            self.state = "ERROR"; self.stop(); raise
        if (ready.get("type") != "ready" or ready.get("status") != "PASS"
                or ready.get("constructorCalls") != 1 or ready.get("warmupCalls") != 1
                or not ready.get("networkRoutesEmpty") or not isinstance(ready.get("workerPid"), int)):
            self.state = "ERROR"; self.stop(); raise TurnStageFailure("STT_EVIDENCE_FAILED")
        self.worker_pid = int(ready["workerPid"]); self.model_load_count = 1; self.state = "READY"

    def transcribe(self, audio: bytes) -> dict[str, object]:
        try:
            with self._lock:
                if self.state != "READY" or not self.process or self.process.poll() is not None:
                    raise RuntimeError("persistent STT worker not ready")
                if self.submission_count >= 16: raise RuntimeError("STT submission limit reached")
                if self.active_job_id is not None: raise RuntimeError("one STT job already active")
                job_id = self.next_job_id; self.next_job_id += 1
                self.submission_count += 1; self.active_job_id = job_id; self.state = "TRANSCRIBING"
        except Exception:
            raise TurnStageFailure("STT_START_FAILED") from None
        if not GPU.acquire("STT"):
            with self._lock: self.active_job_id = None; self.state = "READY"
            raise TurnStageFailure("STT_START_FAILED") from None
        try:
            process = self.process
            if not process or not process.stdin: raise TurnStageFailure("STT_WORKER_FAILED")
            payload = json.dumps({"type":"transcribe", "sessionId":self.session_id, "jobId":job_id,
                                  "audioBase64":base64.b64encode(audio).decode("ascii")}, separators=(",", ":")).encode() + b"\n"
            audio = b""
            with self._io_lock:
                try: process.stdin.write(payload); process.stdin.flush()
                except (BrokenPipeError, OSError): raise TurnStageFailure("STT_WORKER_FAILED") from None
                payload = b""; result = self._read_json()
            if result.get("type") != "transcribed" or result.get("status") != "PASS": raise TurnStageFailure("STT_WORKER_FAILED")
            if (result.get("sessionId") != self.session_id or result.get("jobId") != job_id
                    or result.get("transcribeCalls") != 1 or not result.get("audioReleased")
                    or not result.get("transcriptReleasedAfterWrite")):
                raise TurnStageFailure("STT_EVIDENCE_FAILED") from None
            with self._lock:
                if job_id in self.invalidated_jobs: raise TurnStageFailure("STT_FAILED")
            text = result.get("text")
            try: self.pending_text = clean_text(text)
            except Exception: raise TurnStageFailure("STT_EMPTY_TRANSCRIPT") from None
            self.pending_id = secrets.token_hex(16)
            self.state = "COMPLETED"
            return {"status":"PASS", "text":self.pending_text, "transcriptId":self.pending_id,
                    "jobId":job_id, "workerPid":self.worker_pid, "modelLoads":self.model_load_count,
                    "transcribeSeconds":result.get("transcribeSeconds")}
        except TurnStageFailure:
            self.state = "ERROR"
            raise
        except Exception:
            self.state = "ERROR"
            raise TurnStageFailure("STT_FAILED") from None
        finally:
            with self._lock:
                self.invalidated_jobs.discard(job_id)
                if self.active_job_id == job_id: self.active_job_id = None
                if self.state == "TRANSCRIBING": self.state = "READY"
            GPU.release("STT")

    def consume_approval(self, transcript_id: object, approved_value: object) -> tuple[str, dict[str, object]]:
        approved_text = clean_text(approved_value)
        if approved_text != approved_value: raise ValueError("approved text must already match bounded normalized form")
        with self._lock:
            if self.state != "COMPLETED" or not self.pending_text or not self.pending_id or transcript_id != self.pending_id:
                raise RuntimeError("Transcript approval identity or replay gate rejected")
            original = self.pending_text
            self.pending_text = None
            self.pending_id = None
            self.state = "READY"
        audit = {"originalSha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                 "approvedSha256": hashlib.sha256(approved_text.encode("utf-8")).hexdigest(),
                 "originalChars": len(original), "approvedChars": len(approved_text), "edited": approved_text != original}
        return approved_text, audit

    def discard(self, transcript_id: object) -> None:
        with self._lock:
            if self.state != "COMPLETED" or not self.pending_text or not self.pending_id or transcript_id != self.pending_id:
                raise RuntimeError("Transcript discard identity or replay gate rejected")
            self.pending_text = None
            self.pending_id = None
            self.state = "READY"

    def clear_pending(self) -> None:
        with self._lock:
            self.pending_text = None
            self.pending_id = None
            if self.state == "COMPLETED": self.state = "READY"

    def cancel_active(self) -> None:
        with self._lock:
            if self.active_job_id is not None: self.invalidated_jobs.add(self.active_job_id)
            self.pending_text = None; self.pending_id = None

    def stop(self) -> None:
        with self._lock: process = self.process; self.process = None
        if process and process.poll() is None:
            if process.stdin:
                try: process.stdin.write(b'{"type":"shutdown"}\n'); process.stdin.flush(); process.wait(timeout=10)
                except Exception:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        self.worker_pid = None; self.active_job_id = None; self.pending_text = None; self.pending_id = None
        self.state = "STOPPED"; GPU.release("STT")

STT = SttService()

class ReasoningGateway:
    """Bounded text-only worker using the signed official Codex subscription client."""
    def __init__(self) -> None:
        self.requests = 0
        self.tool_events = 0
        self.last_model = None
        self.last_duration = None
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self.active_process: subprocess.Popen[str] | None = None

    def reason(self, transcript: str, context: list[dict[str, str]]) -> str:
        with self._lock:
            if self.requests >= 5: raise RuntimeError("OpenAI request limit reached")
            prompt = build_prompt(transcript, context)
            self.requests += 1
            command = [sys.executable, str(Path(__file__).resolve().parent.parent / "worker" / "reasoner_worker.py")]
            try:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, encoding="utf-8", errors="replace",
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError: raise TurnStageFailure("REASONER_START_FAILED") from None
            with self._process_lock: self.active_process = process
            try:
                stdout, _stderr = process.communicate(input=json.dumps({"type": "reason", "prompt": prompt, "runtimeVersion": RUNTIME_VERSION}) + "\n", timeout=100)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                raise TurnStageFailure("REASONER_RESPONSE_FAILED") from None
            except Exception:
                raise TurnStageFailure("REASONER_RESPONSE_FAILED") from None
            finally:
                with self._process_lock:
                    if self.active_process is process: self.active_process = None
            try:
                lines = [line for line in stdout.splitlines() if line.strip()]
                if process.returncode != 0 or not lines: raise RuntimeError("restricted reasoning worker failed")
                value = json.loads(lines[-1])
                if value.get("type") != "response" or value.get("runtimeVersion") != RUNTIME_VERSION or value.get("toolEvents") != 0:
                    raise RuntimeError("restricted reasoning evidence rejected")
                self.tool_events += int(value.get("toolEvents", 0)); self.last_model = value.get("model"); self.last_duration = value.get("durationSeconds")
                return validate_response(value.get("text"))
            except TurnStageFailure: raise
            except Exception: raise TurnStageFailure("REASONER_RESPONSE_FAILED") from None

    def cancel(self) -> None:
        with self._process_lock: process = self.active_process
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)

REASONER = ReasoningGateway()
CONVERSATION = ConversationSession()
CONVERSATION_LOCK = threading.RLock()

def conversation_headers(headers: object) -> tuple[str | None, str | None, int | None]:
    getter = getattr(headers, "get")
    session_id, session_token = getter(CONVERSATION_SESSION_HEADER), getter(CONVERSATION_TOKEN_HEADER)
    try: turn_id = int(getter(CONVERSATION_TURN_HEADER, "0"))
    except (TypeError, ValueError): turn_id = None
    return session_id, session_token, turn_id

def cleanup_conversation(*, retain: bool = False, stop_worker: bool = False) -> str | None:
    REASONER.cancel(); VOICE.stop(); STT.cancel_active()
    if stop_worker: STT.stop()
    with CONVERSATION_LOCK:
        if CONVERSATION.state == "OFF":
            if not retain: CONVERSATION.end(retain=False)
            return CONVERSATION.resumable_id
        return CONVERSATION.end(retain=retain, resume_id=CONVERSATION.record_id if retain else None)

def conversation_watchdog(stop_event: threading.Event) -> None:
    while not stop_event.wait(1):
        with CONVERSATION_LOCK: lease_expired, session_expired = CONVERSATION.lease_expired(), CONVERSATION.session_expired()
        if lease_expired or session_expired: cleanup_conversation(retain=session_expired, stop_worker=True)

class MaeveHandler(BaseHTTPRequestHandler):
    server_version, sys_version = "MaeveLoopback/0.3", ""
    def log_message(self, _format_string: str, *_args: object) -> None:
        print("[maeve-loopback] request handled", flush=True)
    def _security_headers(self) -> None:
        self.send_header("Content-Security-Policy", CSP); self.send_header("Permissions-Policy", "microphone=(self), camera=(), geolocation=(), payment=()")
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer"); self.send_header("Cache-Control", "no-store")
    def _finish(self, status: HTTPStatus, content_type: str, body: bytes = b"") -> None:
        self.send_response(status); self._security_headers(); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.end_headers()
        if self.command != "HEAD" and body: self.wfile.write(body)
    def _normalized_path(self) -> str | None:
        if len(self.path) > MAX_REQUEST_TARGET: return None
        try: decoded = unquote(urlsplit(self.path).path, errors="strict")
        except UnicodeDecodeError: return None
        if "\\" in decoded or "\x00" in decoded: return None
        normalized = posixpath.normpath(decoded)
        if not normalized.startswith("/"): normalized = "/" + normalized
        return normalized if decoded == normalized or (decoded == "/" and normalized == "/") else None
    def _authorized(self) -> bool:
        return token_matches(self.headers.get(TOKEN_HEADER))
    def _read_json_body(self) -> dict[str, object] | None:
        if self.headers.get_content_type() != "application/json": return None
        try: length = int(self.headers.get("Content-Length", "0"))
        except ValueError: return None
        if length <= 0 or length > MAX_JSON_BODY: return None
        try: value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError): return None
        return value if isinstance(value, dict) else None
    def _serve(self, head_only: bool = False) -> None:
        if head_only: self.command = "HEAD"
        path = self._normalized_path()
        if path is None: return self._finish(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"Bad request\n")
        if path.startswith("/api/") or path == "/health":
            if not self._authorized(): return self._finish(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found\n")
        if path == "/health":
            health = VOICE.health() | {"sttState": STT.state, "sttSubmissionCount": STT.submission_count,
                                       "reasoningProvider": "OPENAI_CODEX_SUBSCRIPTION", "reasoningModel": "gpt-5.6-sol",
                                       "reasoningRequests": REASONER.requests, "reasoningToolEvents": REASONER.tool_events,
                                       "conversationState": CONVERSATION.state, "conversationTurns": CONVERSATION.turns}
            return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(health, separators=(",", ":"), sort_keys=True).encode())
        if path == "/api/config":
            value = {"microphone":{"approvedLabel":APPROVED_ENDPOINT_HEADER,"approvedSelector":APPROVED_ENDPOINT_SELECTOR}}
            return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(value, separators=(",", ":"), sort_keys=True).encode())
        if path == "/api/audio/stage9.wav":
            if not VOICE.generation_evidence or not diagnostic_audio_available() or WINDOWS_AUDIO is None: return self._finish(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found\n")
            return self._finish(HTTPStatus.OK, "audio/wav", WINDOWS_AUDIO.read_bytes())
        if path == "/api/audio/stage11.wav":
            try: audio = VOICE.take_response_audio(self.headers.get("X-Maeve-Response-Id"))
            except Exception: return self._finish(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found\n")
            return self._finish(HTTPStatus.OK, "audio/wav", audio)
        if path == "/api/audio/stage13.wav":
            try: audio = VOICE.take_response_audio(self.headers.get("X-Maeve-Response-Id"))
            except Exception: return self._finish(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found\n")
            return self._finish(HTTPStatus.OK, "audio/wav", audio)
        if path == "/api/session-evidence":
            value = {"workerReady": VOICE.ready_evidence, "generation": VOICE.generation_evidence, "browser": VOICE.browser_evidence}
            return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(value, separators=(",", ":"), sort_keys=True).encode())
        candidate = ALLOWED_FILES.get(path)
        if candidate is None or not candidate.is_file(): return self._finish(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found\n")
        try: candidate.relative_to(UI_ROOT)
        except ValueError: return self._finish(HTTPStatus.FORBIDDEN, "text/plain; charset=utf-8", b"Forbidden\n")
        body = candidate.read_bytes(); content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}: content_type += "; charset=utf-8"
        self._finish(HTTPStatus.OK, content_type, body)
    def do_GET(self) -> None: self._serve()
    def do_HEAD(self) -> None: self._serve(head_only=True)
    def do_POST(self) -> None:
        path = self._normalized_path()
        if path is None: return self._finish(HTTPStatus.BAD_REQUEST, "text/plain; charset=utf-8", b"Bad request\n")
        if not self._authorized(): return self._finish(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found\n")
        if not valid_origin(self.headers.get("Origin")): return self._finish(HTTPStatus.FORBIDDEN, "application/json; charset=utf-8", b'{"error":"Origin rejected"}')
        if path == "/api/stt/transcribe":
            try: length = int(self.headers.get("Content-Length", "0"))
            except ValueError: length = 0
            error = validate_stt_headers(self.headers.get("Content-Type", ""), length, self.headers)
            if error: return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", json.dumps({"error": error}, separators=(",", ":")).encode())
            audio = self.rfile.read(length)
            if len(audio) != length: return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Incomplete in-memory body"}')
            try:
                result = STT.transcribe(audio)
                audio = b""
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(result, separators=(",", ":"), sort_keys=True).encode())
            except Exception:
                audio = b""
                return self._finish(HTTPStatus.SERVICE_UNAVAILABLE, "application/json; charset=utf-8", b'{"error":"Local STT failed; no retry permitted"}')
        if path == "/api/conversation/turn":
            try: length = int(self.headers.get("Content-Length", "0"))
            except ValueError: length = 0
            error = validate_stt_headers(self.headers.get("Content-Type", ""), length, self.headers)
            if error: return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", json.dumps({"error": error}, separators=(",", ":")).encode())
            audio = self.rfile.read(length)
            if len(audio) != length: return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Incomplete in-memory body"}')
            session_id, session_token, turn_id = conversation_headers(self.headers)
            try:
                try:
                    with CONVERSATION_LOCK: CONVERSATION.claim_turn(session_id, session_token, turn_id)
                except Exception: raise TurnStageFailure("RESPONSE_IDENTITY_FAILED") from None
                stt = STT.transcribe(audio); audio = b""
                try:
                    transcript = clean_text(stt["text"])
                    STT.clear_pending()
                    intent, wait_seconds = classify_local_intent(transcript)
                except Exception: raise TurnStageFailure("INTENT_FAILED") from None
                if intent == "END":
                    resume_id = cleanup_conversation(retain=True, stop_worker=True)
                    return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"status":"ENDED","transcript":transcript,"reason":"LOCAL_SPOKEN_END","resumable":True,"resumeId":resume_id,"stoppingTurn":turn_id,"microphone":"CLOSED","sessionTokenCleared":CONVERSATION.session_token is None,"openAIRequestCreated":False,"openAIRequests":REASONER.requests}, separators=(",", ":")).encode())
                if intent == "WAIT":
                    STT.clear_pending()
                    with CONVERSATION_LOCK:
                        CONVERSATION.complete_control_turn(wait_seconds)
                        next_turn = CONVERSATION.next_turn_id
                    return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"status":"PAUSED","transcript":transcript,"waitSeconds":wait_seconds,"nextTurn":next_turn,"microphone":"CLOSED","openAIRequests":REASONER.requests}, separators=(",", ":")).encode())
                if intent == "EXTEND":
                    STT.clear_pending()
                    with CONVERSATION_LOCK:
                        CONVERSATION.approve_extension(); CONVERSATION.complete_control_turn()
                        next_turn, extensions, remaining = CONVERSATION.next_turn_id, CONVERSATION.extensions, int(CONVERSATION.deadline - time.monotonic())
                    return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"status":"EXTENDED","transcript":transcript,"extensionSeconds":3600,"extensions":extensions,"secondsRemaining":remaining,"nextTurn":next_turn,"microphone":"CLOSED","openAIRequests":REASONER.requests}, separators=(",", ":")).encode())
                try:
                    with CONVERSATION_LOCK:
                        CONVERSATION.authorize(session_id, session_token)
                        if turn_id != CONVERSATION.pending_turn_id: raise RuntimeError("conversation claim became stale")
                        context = list(CONVERSATION.context)
                        CONVERSATION.transition("THINKING")
                except Exception: raise TurnStageFailure("RESPONSE_IDENTITY_FAILED") from None
                response_text = REASONER.reason(transcript, context)
                try:
                    with CONVERSATION_LOCK:
                        CONVERSATION.authorize(session_id, session_token)
                        if turn_id != CONVERSATION.pending_turn_id: raise RuntimeError("conversation ended during reasoning")
                        CONVERSATION.add_turn(transcript, response_text)
                except Exception: raise TurnStageFailure("RESPONSE_IDENTITY_FAILED") from None
                try:
                    response_id = secrets.token_hex(16)
                    result = VOICE.generate_response(response_text, response_id=response_id, response_limit=16,
                                                     require_stt=False)
                except ProviderFailure: raise TurnStageFailure("VOICE_GENERATION_FAILED") from None
                except QwenStageFailure as failure: raise TurnStageFailure(failure.category) from None
                except Exception: raise TurnStageFailure("QWEN_FAILED") from None
                try:
                    VOICE.bind_response(response_id)
                    with CONVERSATION_LOCK: CONVERSATION.bind_response(turn_id, response_id)
                except Exception: raise TurnStageFailure("RESPONSE_IDENTITY_FAILED") from None
                try:
                    response = {"status": "READY_FOR_PLAYBACK", "transcript": transcript, "text": response_text,
                                "audioUrl": "/api/audio/stage13.wav", "audio": result["audio"], "turn": CONVERSATION.turns,
                                "turnId": turn_id, "responseId": response_id}
                    response_body = json.dumps(response, separators=(",", ":"), sort_keys=True).encode()
                except Exception: raise TurnStageFailure("PLAYBACK_PREP_FAILED") from None
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", response_body)
            except Exception as error:
                audio = b""; cleanup_conversation(retain=False, stop_worker=True)
                return self._finish(HTTPStatus.SERVICE_UNAVAILABLE, "application/json; charset=utf-8", turn_failure_payload(error))
        body = self._read_json_body()
        if path == "/api/response/approve":
            if body is None or set(body) != {"action", "runtimeVersion", "transcriptId", "approvedText"} or body.get("action") != "approve-edited-transcript-and-respond" or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact controlled-response approval required"}')
            if GPU.owner != "NONE" or VOICE.response_count >= 2:
                return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"STT/GPU/decision gate rejected"}')
            try:
                approved_transcript, review_audit = STT.consume_approval(body.get("transcriptId"), body.get("approvedText"))
            except Exception:
                return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8",
                                    review_failure_payload("REVIEW_APPROVAL_FAILED"))
            try:
                response_text = REASONER.reason(approved_transcript, [])
            except Exception:
                VOICE.stop()
                return self._finish(HTTPStatus.SERVICE_UNAVAILABLE, "application/json; charset=utf-8",
                                    review_failure_payload("REASONING_FAILED"))
            response_id = secrets.token_hex(16)
            try:
                result = VOICE.generate_response(response_text, response_id=response_id, require_stt=False)
            except ProviderFailure as error:
                VOICE.stop()
                category = "AUDIO_RESPONSE_INVALID" if str(error) == "VOICE_AUDIO_FAILED" else "VOICE_GENERATION_FAILED"
                return self._finish(HTTPStatus.SERVICE_UNAVAILABLE, "application/json; charset=utf-8",
                                    review_failure_payload(category))
            except Exception:
                VOICE.stop()
                return self._finish(HTTPStatus.SERVICE_UNAVAILABLE, "application/json; charset=utf-8",
                                    review_failure_payload("VOICE_GENERATION_FAILED"))
            try:
                VOICE.bind_response(response_id)
                audio = result["audio"]
                response = {"status": "READY_FOR_PLAYBACK", "text": response_text, "audioUrl": "/api/audio/stage13.wav", "audio": audio,
                            "responseId": response_id, "reviewAudit": review_audit}
                response_body = json.dumps(response, separators=(",", ":"), sort_keys=True).encode()
            except Exception:
                VOICE.stop()
                return self._finish(HTTPStatus.SERVICE_UNAVAILABLE, "application/json; charset=utf-8",
                                    review_failure_payload("RESPONSE_PACKAGING_FAILED"))
            return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", response_body)
        if path == "/api/response/discard":
            if body is None or set(body) != {"action", "runtimeVersion", "transcriptId"} or body.get("action") != "discard-local-transcript" or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact transcript discard required"}')
            try:
                STT.discard(body.get("transcriptId"))
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", b'{"status":"DISCARDED"}')
            except Exception:
                return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Transcript discard rejected"}')
        if path == "/api/response/playback-complete":
            if body is None or set(body) != {"result", "runtimeVersion", "responseId"} or body.get("result") not in {"COMPLETED", "FAILED"} or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact playback completion evidence required"}')
            try:
                VOICE.complete_response_playback(body.get("responseId") if isinstance(body.get("responseId"), str) else None)
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", b'{"status":"RESPONSE_COMPLETE"}')
            except Exception:
                return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Response completion gate rejected"}')
        if path == "/api/response/cancel":
            if body is None or set(body) != {"action", "runtimeVersion", "responseId"} or body.get("action") != "cancel-review-response" or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact Review Mode cancellation required"}')
            try:
                status = VOICE.cancel_response(str(body.get("responseId")))
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"status": status, "microphone": "PTT_ONLY_CLOSED"}, separators=(",", ":")).encode())
            except Exception:
                return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Review Mode cancellation rejected"}')
        if path == "/api/speak":
            if RUN_MODE == "PTT_PLAYBACK_ONLY": return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Qwen generation is disabled while PTT mode is active"}')
            if body is None or set(body) != {"text", "runtimeVersion"} or body.get("text") != APPROVED_TEXT or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact approved text and runtime version required"}')
            try:
                result = VOICE.generate(APPROVED_TEXT)
                response = {"status": "READY_FOR_PLAYBACK", "audioUrl": "/api/audio/stage9.wav", "audio": result["audio"]}
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(response, separators=(",", ":"), sort_keys=True).encode())
            except Exception:
                return self._finish(HTTPStatus.SERVICE_UNAVAILABLE, "application/json; charset=utf-8", b'{"error":"Canonical Maeve generation failed; no retry permitted"}')
        if path == "/api/session-evidence":
            if body is None or set(body) != {"runtimeVersion", "stateSequence", "playback", "analyzer"} or body.get("runtimeVersion") != RUNTIME_VERSION or len(json.dumps(body, separators=(",", ":"))) > MAX_JSON_BODY:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Invalid evidence"}')
            VOICE.browser_evidence = body
            return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", b'{"status":"RECORDED"}')
        if path == "/api/conversation/start":
            if body is None or set(body) != {"action", "runtimeVersion", "resumeId", "resumeConfirmed"} or body.get("action") not in {"trusted-physical-start", "trusted-physical-resume"} or body.get("runtimeVersion") != RUNTIME_VERSION or (body.get("resumeId") is not None and not isinstance(body.get("resumeId"), str)) or not isinstance(body.get("resumeConfirmed"), bool):
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact conversation start required"}')
            try:
                resume_id = body.get("resumeId"); is_resume = body.get("action") == "trusted-physical-resume"
                if is_resume != bool(resume_id) or body.get("resumeConfirmed") is not is_resume: raise RuntimeError("Explicit identified resume confirmation required")
                session_id, session_token, record_id = secrets.token_hex(16), secrets.token_hex(32), secrets.token_hex(16)
                with CONVERSATION_LOCK: CONVERSATION.start(session_id, session_token, resume_id, resume_confirmed=is_resume, record_id=record_id)
                response = {"status":"MUTED" if is_resume else "READY","provider":"OPENAI_CODEX_SUBSCRIPTION","sessionId":session_id,
                            "sessionToken":session_token,"conversationId":CONVERSATION.record_id,"resumed":is_resume,"microphone":"CLOSED","nextTurn":1,"timeoutPolicy":{"candidate":True,
                            "noSpeechSeconds":TIMEOUT_POLICY.no_speech_seconds,"graceSeconds":TIMEOUT_POLICY.grace_seconds,
                            "sessionSeconds":TIMEOUT_POLICY.session_seconds}}
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(response, separators=(",", ":")).encode())
            except Exception: return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Conversation start rejected"}')
        if path == "/api/conversation/silence-prompt":
            if body is None or set(body) != {"action", "runtimeVersion", "sessionId", "turnId"} or body.get("action") != "silence-prompt" or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact silence prompt required"}')
            try:
                session_token = self.headers.get(CONVERSATION_TOKEN_HEADER)
                with CONVERSATION_LOCK: CONVERSATION.claim_turn(body.get("sessionId"), session_token, body.get("turnId"))
                response_id = secrets.token_hex(16)
                result = VOICE.generate_response(STILL_THERE_PROMPT, response_id=response_id, response_limit=16, require_stt=False)
                VOICE.bind_response(response_id)
                with CONVERSATION_LOCK: CONVERSATION.bind_response(body["turnId"], response_id)
                response = {"status":"READY_FOR_PLAYBACK","text":STILL_THERE_PROMPT,"audioUrl":"/api/audio/stage13.wav",
                            "audio":result["audio"],"turnId":body["turnId"],"responseId":response_id,"openAIRequests":REASONER.requests}
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(response, separators=(",", ":"), sort_keys=True).encode())
            except Exception:
                cleanup_conversation(retain=False, stop_worker=True)
                return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Silence prompt rejected"}')
        if path == "/api/conversation/session-warning":
            if body is None or set(body) != {"action", "runtimeVersion", "sessionId", "turnId", "warning"} or body.get("action") != "session-warning" or body.get("runtimeVersion") != RUNTIME_VERSION or body.get("warning") not in {"FIVE_MINUTE_WARNING", "FINAL_59_MINUTE_WARNING"}:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact session warning required"}')
            try:
                session_token = self.headers.get(CONVERSATION_TOKEN_HEADER)
                with CONVERSATION_LOCK:
                    expected_sent = CONVERSATION.warning_55_sent if body["warning"] == "FIVE_MINUTE_WARNING" else CONVERSATION.warning_59_sent
                    if not expected_sent: raise RuntimeError("session warning was not due")
                    CONVERSATION.claim_turn(body.get("sessionId"), session_token, body.get("turnId"))
                text = SESSION_WARNING_55_PROMPT if body["warning"] == "FIVE_MINUTE_WARNING" else SESSION_WARNING_59_PROMPT
                response_id = secrets.token_hex(16)
                result = VOICE.generate_response(text, response_id=response_id, response_limit=128, require_stt=False)
                VOICE.bind_response(response_id)
                with CONVERSATION_LOCK: CONVERSATION.bind_response(body["turnId"], response_id)
                response = {"status":"READY_FOR_PLAYBACK","text":text,"audioUrl":"/api/audio/stage13.wav","audio":result["audio"],"turnId":body["turnId"],"responseId":response_id,"warning":body["warning"],"openAIRequests":REASONER.requests}
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(response, separators=(",", ":"), sort_keys=True).encode())
            except Exception:
                cleanup_conversation(retain=False, stop_worker=True)
                return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Session warning rejected"}')
        if path == "/api/conversation/playback-complete":
            if body is None or set(body) != {"action", "runtimeVersion", "sessionId", "turnId", "responseId"} or body.get("action") != "conversation-playback-complete" or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact conversation playback evidence required"}')
            try:
                session_token = self.headers.get(CONVERSATION_TOKEN_HEADER)
                with CONVERSATION_LOCK: CONVERSATION.authorize_identity(body.get("sessionId"), session_token)
                VOICE.complete_response_playback(body.get("responseId"))
                with CONVERSATION_LOCK:
                    CONVERSATION.complete_playback(body.get("sessionId"), session_token, body.get("turnId"), body.get("responseId"))
                    next_turn = CONVERSATION.next_turn_id
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"status":"READY","nextTurn":next_turn}, separators=(",", ":")).encode())
            except Exception: return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Conversation playback completion rejected"}')
        if path == "/api/conversation/mute":
            if body is None or set(body) != {"action", "runtimeVersion", "sessionId"} or body.get("action") not in {"mute", "unmute"} or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact mute action required"}')
            try:
                session_token = self.headers.get(CONVERSATION_TOKEN_HEADER)
                with CONVERSATION_LOCK:
                    CONVERSATION.authorize(body.get("sessionId"), session_token)
                    if body["action"] == "mute": CONVERSATION.mute()
                    else: CONVERSATION.unmute()
                    next_turn = CONVERSATION.next_turn_id
                VOICE.stop()
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"status":CONVERSATION.state,"nextTurn":next_turn}, separators=(",", ":")).encode())
            except Exception: return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Mute action rejected"}')
        if path == "/api/conversation/heartbeat":
            if body is None or set(body) != {"action", "runtimeVersion", "sessionId"} or body.get("action") != "heartbeat" or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact conversation heartbeat required"}')
            try:
                with CONVERSATION_LOCK:
                    CONVERSATION.authorize(body.get("sessionId"), self.headers.get(CONVERSATION_TOKEN_HEADER))
                    warning = CONVERSATION.next_session_warning(); remaining = max(0, int(CONVERSATION.deadline - time.monotonic()))
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps({"status":"ALIVE","warning":warning,"secondsRemaining":remaining}, separators=(",", ":")).encode())
            except Exception: return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Conversation heartbeat rejected"}')
        if path in {"/api/conversation/end", "/api/conversation/cancel", "/api/conversation/timeout"}:
            expected = {"/api/conversation/end":"end", "/api/conversation/cancel":"cancel", "/api/conversation/timeout":"timeout"}[path]
            if body is None or set(body) != {"action", "runtimeVersion", "sessionId"} or body.get("action") != expected or body.get("runtimeVersion") != RUNTIME_VERSION:
                return self._finish(HTTPStatus.BAD_REQUEST, "application/json; charset=utf-8", b'{"error":"Exact conversation cleanup required"}')
            try:
                session_token = self.headers.get(CONVERSATION_TOKEN_HEADER)
                with CONVERSATION_LOCK: CONVERSATION.authorize_identity(body.get("sessionId"), session_token)
                resume_id = cleanup_conversation(retain=expected == "timeout", stop_worker=expected != "cancel")
                response = {"status":"OFF","contextCleared":True,"sessionTokenCleared":True,"reason":expected.upper(),
                            "resumeId":resume_id,"resumable":bool(resume_id),"microphone":"CLOSED"}
                return self._finish(HTTPStatus.OK, "application/json; charset=utf-8", json.dumps(response, separators=(",", ":")).encode())
            except Exception: return self._finish(HTTPStatus.CONFLICT, "application/json; charset=utf-8", b'{"error":"Conversation cleanup rejected"}')
        self._finish(HTTPStatus.METHOD_NOT_ALLOWED, "text/plain; charset=utf-8", b"Method not allowed\n")
    def _method_not_allowed(self) -> None: self._finish(HTTPStatus.METHOD_NOT_ALLOWED, "text/plain; charset=utf-8", b"Method not allowed\n")
    do_PUT = _method_not_allowed; do_DELETE = _method_not_allowed; do_PATCH = _method_not_allowed; do_OPTIONS = _method_not_allowed

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Maeve V2 loopback-only Stage 13 broker")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--controlled-conversation", action="store_true")
    parser.add_argument("--voice-provider", choices=("elevenlabs", "qwen"), default="elevenlabs")
    parser.add_argument("--mock-elevenlabs", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()

def main() -> None:
    global RUN_MODE
    configure_runtime()
    args = parse_args()
    if args.port != DEFAULT_PORT: raise SystemExit("Stage 13 is restricted to 127.0.0.1:48177.")
    if not args.controlled_conversation: raise SystemExit("Explicit --controlled-conversation mode is required.")
    if not TOKEN_PATTERN.fullmatch(runtime_token()): raise SystemExit("A fresh 64-character hexadecimal runtime token is required.")
    VOICE.selected_provider = args.voice_provider.upper()
    if args.mock_elevenlabs:
        if VOICE.selected_provider != "ELEVENLABS": raise SystemExit("Mock provider requires ElevenLabs selection")
        VOICE.cloud = MockElevenLabsProvider(UsageLedger(Path(os.environ.get("TEMP", ".")) / "maeve-mock-usage.json", UsageLimits()))
    RUN_MODE = "CONTROLLED_CONVERSATION"
    VOICE.resume_validated_audio()
    STT.start()
    server = ThreadingHTTPServer((LOOPBACK_HOST, DEFAULT_PORT), MaeveHandler)
    watchdog_stop = threading.Event(); watchdog = threading.Thread(target=conversation_watchdog, args=(watchdog_stop,), name="maeve-conversation-watchdog", daemon=True); watchdog.start()
    print("Maeve V2 Stage 13 runtime ready on 127.0.0.1:48177", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        watchdog_stop.set(); watchdog.join(timeout=2); server.server_close(); REASONER.cancel(); VOICE.stop(); STT.stop(); CONVERSATION.end(); RUN_MODE = "STOPPED"; os.environ.pop(TOKEN_ENV, None)
        print("Maeve V2 Stage 13 runtime stopped.", flush=True)

if __name__ == "__main__": main()
