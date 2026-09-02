"""Static and pure-unit Stage 10F QA. Opens no listener, browser, WSL, model, or microphone."""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
TOKEN = "a" * 64
os.environ["MAEVE_RUNTIME_TOKEN"] = TOKEN
sys.path.insert(0, str(ROOT / "broker"))

import server as broker  # noqa: E402

broker.RUNTIME_CONFIG = {
    "stt_distribution": "Maeve-STT", "stt_python": "/opt/stt/python",
    "stt_worker_path": "/mnt/c/portable/stt_worker.py", "stt_model_path": "/srv/models/stt",
    "qwen": {"distribution":"Maeve-Qwen-TTS", "python":"/opt/qwen/python",
             "worker_path":"/mnt/c/portable/qwen_worker.py", "model_path":"/srv/models/qwen",
             "voice_identity_path":"/srv/voices/maeve"},
}


def main() -> None:
    server_source = (ROOT / "broker" / "server.py").read_text(encoding="utf-8")
    runtime_source = (ROOT / "ui" / "scripts" / "runtime.js").read_text(encoding="utf-8")
    ptt_source = (ROOT / "ui" / "scripts" / "ptt-controller.js").read_text(encoding="utf-8")
    html_source = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    css_source = (ROOT / "ui" / "styles" / "runtime-stage1.css").read_text(encoding="utf-8")
    worker_source = (ROOT / "worker" / "stt_worker.py").read_text(encoding="utf-8")
    qwen_source = (ROOT / "worker" / "qwen_worker.py").read_text(encoding="utf-8")
    launcher_path = ROOT / "scripts" / "start-windows.py"
    launcher_source = launcher_path.read_text(encoding="utf-8")
    launcher_spec = importlib.util.spec_from_file_location("maeve_start_windows", launcher_path)
    assert launcher_spec and launcher_spec.loader
    launcher = importlib.util.module_from_spec(launcher_spec)
    launcher_spec.loader.exec_module(launcher)

    ast.parse(server_source)
    ast.parse(worker_source)
    ast.parse(qwen_source)
    assert broker.RUNTIME_VERSION == "0.5.0-stage13"
    assert broker.LOOPBACK_HOST == "127.0.0.1" and broker.DEFAULT_PORT == 48177
    assert broker.token_matches(TOKEN) and not broker.token_matches(None) and not broker.token_matches("b" * 64)
    assert broker.valid_origin("http://127.0.0.1:48177") and not broker.valid_origin("http://localhost:48177")

    valid_health = {"broker":"READY", "sttState":"READY", "sttSubmissionCount":0,
                    "reasoningRequests":0, "runMode":"CONTROLLED_CONVERSATION"}
    assert launcher._validated_health(json.dumps(valid_health).encode()) == valid_health
    for invalid in (b"not-json", b"[]", json.dumps(valid_health | {"sttState":"WARMING"}).encode(),
                    json.dumps(valid_health | {"sttSubmissionCount":1}).encode()):
        try: launcher._validated_health(invalid)
        except RuntimeError: pass
        else: raise AssertionError("invalid readiness response was accepted")
    assert launcher.STARTUP_DEADLINE_SECONDS == 120.0
    assert launcher.READINESS_POLL_INTERVAL_SECONDS == 0.2
    assert launcher_source.count("broker = children.start(") == 1
    assert launcher_source.index("health = wait_for_health(token, broker)") < launcher_source.index("if args.open_browser:")
    assert "capture=True" in launcher_source and "process.send_signal(signal.CTRL_BREAK_EVENT)" in launcher_source
    assert "broker_env[TOKEN_ENV] = token" in launcher_source
    assert "[str(PYTHON_EXE), str(SERVER)" in launcher_source and "TOKEN_ENV" not in launcher_source.split("broker = children.start(", 1)[1].split("cwd=SERVER.parent", 1)[0]
    assert "while time.monotonic() < deadline" in launcher_source and "children.start(" not in launcher_source.split("def wait_for_health", 1)[1].split("def parse_arguments", 1)[0]
    assert all(secret not in launcher_source for secret in (TOKEN, "MaeveV2/ElevenLabsPrimary"))

    class ExitedBroker:
        returncode = 7
        def poll(self): return 7
        def communicate(self, timeout=1): return f"safe {TOKEN}".encode(), b"safe stderr"
    with patch.object(launcher.time, "monotonic", side_effect=(0.0, 0.1)):
        try: launcher.wait_for_health(TOKEN, ExitedBroker())
        except RuntimeError as error:
            assert "exited before readiness with code 7" in str(error) and "safe stderr" in str(error)
            assert TOKEN not in str(error) and "[REDACTED]" in str(error)
        else: raise AssertionError("owned broker exit was not detected immediately")

    class RunningBroker:
        returncode = None
        def poll(self): return None
    with patch.object(launcher.time, "monotonic", side_effect=(0.0, 121.0)):
        try: launcher.wait_for_health(TOKEN, RunningBroker())
        except RuntimeError as error: assert "timed out after 120s" in str(error)
        else: raise AssertionError("finite readiness timeout was not enforced")
    rejected = launcher.urllib.error.HTTPError(launcher.URL if hasattr(launcher, "URL") else "http://127.0.0.1:48177/health", 404, "Not found", {}, None)
    with patch.object(launcher.time, "monotonic", side_effect=(0.0, 0.1)), patch.object(launcher.urllib.request, "urlopen", side_effect=rejected):
        try: launcher.wait_for_health(TOKEN, RunningBroker())
        except RuntimeError as error: assert "authentication rejected" in str(error)
        else: raise AssertionError("incorrect readiness authentication was not rejected")

    good_headers = {"X-Endpoint-Label": broker.APPROVED_ENDPOINT_HEADER, "X-Exact-Device-Match": "true",
                    "X-All-Tracks-Ended": "true", "X-Recording-Duration-Ms": "5500", "X-Closure-Latency-Ms": "1.4"}
    assert broker.validate_stt_headers("audio/webm;codecs=opus", 1024, good_headers) is None
    assert broker.validate_stt_headers("audio/wav", 1024, good_headers) == "unsupported audio type"
    assert broker.validate_stt_headers("audio/webm;codecs=opus", 0, good_headers) == "audio size rejected"
    assert broker.validate_stt_headers("audio/webm;codecs=opus", broker.MAX_AUDIO_BYTES + 1, good_headers) == "audio size rejected"
    for changed_key in ("X-Endpoint-Label", "X-Exact-Device-Match", "X-All-Tracks-Ended"):
        rejected = dict(good_headers); rejected[changed_key] = "rejected"
        assert broker.validate_stt_headers("audio/webm;codecs=opus", 1024, rejected) is not None

    gpu = broker.ModelScheduler()
    assert gpu.owner == "NONE" and gpu.acquire("STT") and gpu.owner == "STT"
    assert not gpu.acquire("QWEN") and gpu.owner == "STT"
    gpu.release("QWEN"); assert gpu.owner == "STT"
    gpu.release("STT"); assert gpu.owner == "NONE"
    assert gpu.acquire("QWEN") and not gpu.acquire("STT"); gpu.release("QWEN")

    stt = broker.SttService()
    stt.state, stt.pending_text, stt.pending_id = "COMPLETED", "Maeve original text", "1" * 32
    approved, audit = stt.consume_approval("1" * 32, "Maeve edited text")
    assert approved == "Maeve edited text" and audit["edited"] is True
    assert audit["originalSha256"] != audit["approvedSha256"] and "Maeve" not in str(audit)
    assert stt.pending_text is None and stt.pending_id is None
    try: stt.consume_approval("1" * 32, "duplicate")
    except RuntimeError: pass
    else: raise AssertionError("duplicate approval was accepted")
    stt.state, stt.pending_text, stt.pending_id = "COMPLETED", "retain me", "2" * 32
    try: stt.consume_approval("2" * 32, "   ")
    except ValueError: pass
    else: raise AssertionError("empty approved text was accepted")
    assert stt.pending_text == "retain me" and stt.pending_id == "2" * 32
    try: stt.consume_approval("2" * 32, "changed  spacing")
    except ValueError: pass
    else: raise AssertionError("silently normalized approved text was accepted")
    assert stt.pending_text == "retain me" and stt.pending_id == "2" * 32
    try: stt.consume_approval("2" * 32, "x" * 801)
    except ValueError: pass
    else: raise AssertionError("oversize approved text was accepted")
    assert stt.pending_text == "retain me" and stt.pending_id == "2" * 32
    stt.discard("2" * 32); assert stt.pending_text is None and stt.pending_id is None

    def worker_result(job_id=1, *, text="Maeve valid transcript", **changes):
        value = {"type":"transcribed", "status":"PASS", "sessionId":"f"*32, "jobId":job_id,
                 "transcribeCalls":1, "audioReleased":True, "transcriptReleasedAfterWrite":True,
                 "text":text, "transcribeSeconds":0.5}
        value.update(changes)
        return value

    class FakeSttProcess:
        def __init__(self): self.stdin, self.returncode = io.BytesIO(), None
        def poll(self): return self.returncode
        def wait(self, timeout=None): self.returncode = 0; return 0
        def terminate(self): self.returncode = 1
        def kill(self): self.returncode = 1

    def stt_case(fake, expected):
        broker.GPU = broker.ModelScheduler(); service = broker.SttService()
        service.process=FakeSttProcess(); service.state="READY"; service.session_id="f"*32
        service.worker_pid=1234; service.worker_start_count=1; service.model_load_count=1
        kwargs = {"side_effect": fake} if isinstance(fake, BaseException) else {"return_value": fake}
        with patch.object(service, "_read_json", **kwargs) as read:
            try:
                result = service.transcribe(b"synthetic-container-bytes")
                actual = "PASS"
                assert result["text"] == "Maeve valid transcript" and service.pending_text == result["text"]
                transcript_id = result["transcriptId"]
                approved, _audit = service.consume_approval(transcript_id, result["text"])
                assert approved == result["text"] and service.pending_text is None
                try: service.consume_approval(transcript_id, result["text"])
                except RuntimeError: pass
                else: raise AssertionError("matching transcript replay was accepted")
            except broker.TurnStageFailure as error:
                actual = error.category
                payload = json.loads(broker.turn_failure_payload(error))
                assert payload == {"error": "Controlled conversation turn failed; no automatic retry", "failureCategory": expected}
                assert all(private not in json.dumps(payload) for private in ("PRIVATE", "synthetic-container-bytes", "Maeve valid transcript"))
            assert read.call_count == 1 and actual == expected
            assert broker.GPU.owner == "NONE"

    stt_case(worker_result(), "PASS")
    stt_case(broker.TurnStageFailure("STT_TIMEOUT"), "STT_TIMEOUT")
    stt_case(worker_result(type="rejected", status="FAIL"), "STT_WORKER_FAILED")
    stt_case(worker_result(sessionId="e"*32), "STT_EVIDENCE_FAILED")
    stt_case(worker_result(text=""), "STT_EMPTY_TRANSCRIPT")
    stt_case(worker_result(text=None), "STT_EMPTY_TRANSCRIPT")

    broker.GPU = broker.ModelScheduler(); persistent = broker.SttService()
    persistent.process=FakeSttProcess(); persistent.state="READY"; persistent.session_id="f"*32
    persistent.worker_pid=1234; persistent.worker_start_count=1; persistent.model_load_count=1
    with patch.object(persistent, "_read_json", side_effect=[worker_result(i) for i in range(1,6)]) as read:
        for expected_job in range(1,6):
            assert persistent.transcribe(b"fixed-safe-audio")["jobId"] == expected_job
            persistent.clear_pending()
        assert read.call_count == 5 and persistent.worker_start_count == persistent.model_load_count == 1
    persistent.active_job_id=6; persistent.cancel_active(); assert 6 in persistent.invalidated_jobs

    voice = broker.VoiceWorker("QWEN")
    assert voice.cancel_response("3" * 32) == "NO_ACTIVE_RESPONSE"
    voice.active_response_id, voice.response_audio, voice.response_audio_served = "4" * 32, b"wav", True
    assert voice.cancel_response("4" * 32) == "CANCELLED"
    assert voice.response_audio is None and voice.active_response_id is None and voice.state == "IDLE"
    assert voice.cancel_response("4" * 32) == "ALREADY_CANCELLED"

    broker.STT.state = "READY"
    review_voice = broker.VoiceWorker("ELEVENLABS")
    review_generated = {"type":"generated", "status":"PASS", "text":"Maeve safe response",
                        "audio":{"bytes":4800, "sha256":"0"*64, "sampleRate":24000,
                                 "channels":1, "frames":2400, "durationSeconds":0.1,
                                 "format":"RIFF/WAVE PCM-16"}}
    with patch.object(review_voice.cloud, "generate_response", return_value=review_generated) as cloud_generate:
        try: review_voice.generate_response("Maeve safe response", response_id="7"*32)
        except broker.QwenStageFailure as error: assert error.category == "QWEN_START_FAILED"
        else: raise AssertionError("post-approval STT READY state incorrectly passed the transcription-pending gate")
        assert review_voice.generate_response("Maeve safe response", response_id="7"*32, require_stt=False) == review_generated
        assert cloud_generate.call_count == 1
    review_voice.stop()

    broker.GPU = broker.ModelScheduler(); broker.STT.state = "READY"
    controlled_cloud = broker.VoiceWorker("ELEVENLABS")
    with (patch.object(controlled_cloud.cloud, "generate_response", return_value=review_generated) as cloud_generate,
          patch.object(controlled_cloud, "start_for_response") as qwen_start):
        assert controlled_cloud.generate_response("Maeve safe response", response_id="8"*32,
                                                  response_limit=16, require_stt=False) == review_generated
        assert cloud_generate.call_count == 1 and qwen_start.call_count == 0
        assert controlled_cloud.process is None and controlled_cloud.qwen_start_count == 0 and broker.GPU.owner == "NONE"
        assert controlled_cloud.selected_provider == controlled_cloud.health()["voiceProvider"]["provider"] == "ELEVENLABS"
        assert controlled_cloud.health()["qwenReadyRequired"] is False
    controlled_cloud.stop()

    missing_cloud = broker.VoiceWorker("ELEVENLABS")
    with (patch.object(missing_cloud.cloud, "generate_response", side_effect=broker.ProviderFailure("VOICE_CREDENTIAL_MISSING")) as cloud_generate,
          patch.object(missing_cloud, "start_for_response") as qwen_start):
        try: missing_cloud.generate_response("Maeve safe response", response_id="9"*32, require_stt=False)
        except broker.ProviderFailure as error: assert str(error) == "VOICE_CREDENTIAL_MISSING"
        else: raise AssertionError("missing ElevenLabs credential did not fail visibly")
        assert cloud_generate.call_count == 1 and qwen_start.call_count == 0
        assert missing_cloud.process is None and missing_cloud.qwen_start_count == 0 and broker.GPU.owner == "NONE"
        assert missing_cloud.response_count == 0 and missing_cloud.state == "ERROR"
    missing_cloud.stop()

    class FakeVoiceProcess:
        def __init__(self, *, stdout="", returncode=None):
            self.stdin, self.stdout, self.stderr = io.StringIO(), io.StringIO(stdout), io.StringIO()
            self.returncode = returncode
        def poll(self): return self.returncode
        def wait(self, timeout=None): self.returncode = 0; return 0
        def terminate(self): self.returncode = 1
        def kill(self): self.returncode = 1

    def qwen_case(response_or_error, expected):
        broker.GPU = broker.ModelScheduler(); broker.STT.state = "COMPLETED"
        service = broker.VoiceWorker("QWEN")
        def start_worker():
            assert broker.GPU.acquire("QWEN")
            service.process = FakeVoiceProcess(); service.state = "IDLE"
        kwargs = {"side_effect": response_or_error} if isinstance(response_or_error, BaseException) else {"return_value": response_or_error}
        with patch.object(service, "start_for_response", side_effect=start_worker) as start, patch.object(service, "_read_json", **kwargs) as read:
            try:
                result = service.generate_response("Maeve safe response")
                actual = "PASS"
                assert result["audio"]["bytes"] == len(service.response_audio or b"")
                response_id = "5" * 32; service.bind_response(response_id)
                try: service.take_response_audio("6" * 32)
                except RuntimeError: pass
                else: raise AssertionError("mismatched audio identity was accepted")
                accepted = service.take_response_audio(response_id)
                assert accepted == b"RIFF-safe-audio"
                try: service.take_response_audio(response_id)
                except RuntimeError: pass
                else: raise AssertionError("audio replay was accepted")
                service.complete_response_playback(response_id)
            except broker.QwenStageFailure as error:
                actual = error.category
                payload = json.loads(broker.turn_failure_payload(broker.TurnStageFailure(error.category)))
                assert payload["failureCategory"] == expected
                assert all(private not in json.dumps(payload) for private in ("PRIVATE", "Maeve safe response", "RIFF-safe-audio"))
            assert start.call_count == 1 and read.call_count == 1 and actual == expected
            assert broker.GPU.owner == "NONE"

    safe_audio = b"RIFF-safe-audio"
    safe_response = {"type":"generated", "status":"PASS", "text":"Maeve safe response",
                     "audioBase64":base64.b64encode(safe_audio).decode("ascii"),
                     "audio":{"bytes":len(safe_audio), "sha256":hashlib.sha256(safe_audio).hexdigest(), "sampleRate":24000, "channels":1}}
    qwen_case(dict(safe_response), "PASS")
    qwen_case(broker.QwenStageFailure("QWEN_TIMEOUT"), "QWEN_TIMEOUT")
    qwen_case({"type":"error", "error":"PRIVATE WORKER ERROR"}, "QWEN_WORKER_FAILED")
    qwen_case(broker.QwenStageFailure("QWEN_PROTOCOL_MISSING"), "QWEN_PROTOCOL_MISSING")
    qwen_case(broker.QwenStageFailure("QWEN_PROTOCOL_INVALID_JSON"), "QWEN_PROTOCOL_INVALID_JSON")
    qwen_case(broker.QwenStageFailure("QWEN_PROTOCOL_NON_OBJECT"), "QWEN_PROTOCOL_NON_OBJECT")
    qwen_case({"type":"generated", "status":"PASS", "text":"Maeve safe response", "audio":{}}, "QWEN_PROTOCOL_SCHEMA_FAILED")
    qwen_case(broker.QwenStageFailure("QWEN_PROTOCOL_FAILED"), "QWEN_PROTOCOL_FAILED")
    qwen_case({"type":"generated", "status":"FAIL", "text":"PRIVATE RESPONSE", "audioBase64":"", "audio":{}}, "QWEN_EVIDENCE_FAILED")
    qwen_case({"type":"generated", "status":"PASS", "text":"Maeve safe response", "audioBase64":"PRIVATE INVALID", "audio":{}}, "QWEN_AUDIO_FAILED")
    qwen_case(RuntimeError("PRIVATE UNKNOWN"), "QWEN_FAILED")

    broker.GPU = broker.ModelScheduler(); start_voice = broker.VoiceWorker("QWEN")
    with patch.object(broker.subprocess, "Popen", side_effect=OSError("PRIVATE START")):
        try: start_voice.start_for_response()
        except broker.QwenStageFailure as error: assert error.category == "QWEN_START_FAILED"
        else: raise AssertionError("Qwen process-start failure was accepted")
    assert broker.GPU.owner == "NONE" and start_voice.process is None

    def protocol_case(stdout, expected, *, returncode=None):
        service = broker.VoiceWorker("QWEN"); service.process = FakeVoiceProcess(stdout=stdout, returncode=returncode)
        try: service._read_json(0.5)
        except broker.QwenStageFailure as error: assert error.category == expected
        else: raise AssertionError(f"Qwen stdout protocol case was accepted: {expected}")

    protocol_case("", "QWEN_PROTOCOL_MISSING", returncode=0)
    protocol_case("PRIVATE INVALID JSON\n", "QWEN_PROTOCOL_INVALID_JSON")
    protocol_case("\ufeff{\"type\":\"generated\"}\n", "QWEN_PROTOCOL_INVALID_JSON")
    protocol_case("PRIVATE WARNING\n{\"type\":\"generated\"}\n", "QWEN_PROTOCOL_INVALID_JSON")
    protocol_case('{"type":"generated"} PRIVATE TRAILING\n', "QWEN_PROTOCOL_INVALID_JSON")
    protocol_case("[]\n", "QWEN_PROTOCOL_NON_OBJECT")
    protocol_case('"scalar"\n', "QWEN_PROTOCOL_NON_OBJECT")
    protocol_case("null\n", "QWEN_PROTOCOL_NON_OBJECT")
    framed_voice = broker.VoiceWorker("QWEN"); framed_voice.process = FakeVoiceProcess(stdout='{"type":"generated"}\nPRIVATE TRAILING FRAME\n')
    assert framed_voice._read_json(0.5) == {"type":"generated"}
    try: framed_voice._read_json(0.5)
    except broker.QwenStageFailure as error: assert error.category == "QWEN_PROTOCOL_INVALID_JSON"
    else: raise AssertionError("trailing non-protocol stdout frame was accepted")
    class RaisingStdout:
        def readline(self): raise OSError("PRIVATE READ ERROR")
    unknown_voice = broker.VoiceWorker("QWEN"); unknown_voice.process = FakeVoiceProcess(); unknown_voice.process.stdout = RaisingStdout()
    try: unknown_voice._read_json(0.5)
    except broker.QwenStageFailure as error: assert error.category == "QWEN_PROTOCOL_FAILED"
    else: raise AssertionError("unknown Qwen protocol failure was accepted")
    worker_voice = broker.VoiceWorker("QWEN"); worker_voice.process = FakeVoiceProcess(stdout="", returncode=1)
    try: worker_voice._read_json(0.5)
    except broker.QwenStageFailure as error: assert error.category == "QWEN_WORKER_FAILED"
    else: raise AssertionError("Qwen nonzero exit was accepted")
    class BlockingStdout:
        def readline(self): threading.Event().wait(0.2); return ""
    timeout_voice = broker.VoiceWorker("QWEN"); timeout_voice.process = FakeVoiceProcess(); timeout_voice.process.stdout = BlockingStdout()
    try: timeout_voice._read_json(0.01)
    except broker.QwenStageFailure as error: assert error.category == "QWEN_TIMEOUT"
    else: raise AssertionError("Qwen stdout timeout was accepted")

    broker.GPU = broker.ModelScheduler(); schema_voice = broker.VoiceWorker("QWEN")
    with patch.object(broker.subprocess, "Popen", return_value=FakeVoiceProcess(stdout='{"type":"ready"}\n')):
        try: schema_voice.start_for_response()
        except broker.QwenStageFailure as error: assert error.category == "QWEN_PROTOCOL_SCHEMA_FAILED"
        else: raise AssertionError("invalid Qwen ready schema was accepted")
    assert broker.GPU.owner == "NONE" and schema_voice.process is None

    assert server_source.count("ThreadingHTTPServer((LOOPBACK_HOST, DEFAULT_PORT)") == 1
    assert "--controlled-conversation" in server_source and "VOICE.start()" not in server_source
    assert '"unshare", "--net"' in server_source and 'RUNTIME_CONFIG["stt_distribution"]' in server_source
    assert "microphone=(self)" in server_source and "Access-Control-Allow-Origin" not in server_source
    assert "request handled" in server_source and "self.path" not in server_source.split("def log_message", 1)[1].split("def _security_headers", 1)[0]
    assert "stderr_tail" not in server_source and "for _line in self.process.stderr: pass" in server_source
    assert all(category in server_source for category in ("QWEN_PROTOCOL_MISSING","QWEN_PROTOCOL_INVALID_JSON","QWEN_PROTOCOL_NON_OBJECT","QWEN_PROTOCOL_SCHEMA_FAILED","QWEN_PROTOCOL_FAILED"))
    assert qwen_source.count("print(") == 0 and "def send(value):" in qwen_source
    assert qwen_source.index("_PROTOCOL_FD = os.dup(sys.stdout.fileno())") < qwen_source.index("import numpy as np")
    assert qwen_source.index("os.dup2(_NULL_STDOUT_FD, sys.stdout.fileno(), inheritable=False)") < qwen_source.index("from qwen_tts import")
    assert "os.set_inheritable(_PROTOCOL_FD, False)" in qwen_source and "os.open(os.devnull, os.O_WRONLY)" in qwen_source
    assert '.encode("utf-8")' in qwen_source and "utf-8-sig" not in qwen_source
    assert "os.write(_PROTOCOL_FD, view)" in qwen_source and "protocol object required" in qwen_source
    assert qwen_source.count("sys.stdout") == 2 and "sys.stderr" not in qwen_source
    isolation_probe = r'''
import builtins, json, runpy, sys, types
for name in ("numpy", "soundfile", "torch"):
    sys.modules[name] = types.ModuleType(name)
safetensors = types.ModuleType("safetensors"); safetensors.safe_open = object(); sys.modules["safetensors"] = safetensors
qwen_tts = types.ModuleType("qwen_tts"); qwen_tts.Qwen3TTSModel = object; qwen_tts.VoiceClonePromptItem = object; sys.modules["qwen_tts"] = qwen_tts
real_import = builtins.__import__
def noisy_import(name, *args, **kwargs):
    if name.split(".", 1)[0] in {"numpy", "soundfile", "torch", "safetensors", "qwen_tts"}:
        print("PRIVATE_IMPORT_DIAGNOSTIC", flush=True)
    return real_import(name, *args, **kwargs)
builtins.__import__ = noisy_import
scope = runpy.run_path(sys.argv[1], run_name="qwen_protocol_isolation_probe")
print("PRIVATE_BEFORE_GENERATION", flush=True)
print("PRIVATE_DURING_GENERATION", flush=True)
scope["send"]({"type":"generated","status":"PASS","attempt":1})
print("PRIVATE_AFTER_GENERATION", flush=True)
sys.stderr.write("PRIVATE_STDERR_DIAGNOSTIC\n"); sys.stderr.flush()
'''
    isolated = subprocess.run([sys.executable, "-c", isolation_probe, str(ROOT / "worker" / "qwen_worker.py")],
                              capture_output=True, text=True, encoding="utf-8", errors="strict", timeout=10, check=False)
    assert isolated.returncode == 0
    assert isolated.stdout == '{"type":"generated","status":"PASS","attempt":1}\n'
    assert "PRIVATE" not in isolated.stdout and isolated.stderr == "PRIVATE_STDERR_DIAGNOSTIC\n"
    voice_block = server_source.split("def generate_response", 1)[1].split("def bind_response", 1)[0]
    assert voice_block.index("response = self._read_json(QWEN_GENERATION_TIMEOUT_SECONDS)") < voice_block.index("self.generation_evidence = response") < voice_block.index("self.stop()")
    review_stt_route = server_source.split('if path == "/api/stt/transcribe":', 1)[1].split('if path == "/api/conversation/turn":', 1)[0]
    assert "failureCategory" not in review_stt_route and "Local STT failed; no retry permitted" in review_stt_route
    review_response_route = server_source.split('if path == "/api/response/approve":', 1)[1].split('if path == "/api/response/discard":', 1)[0]
    assert all(value in review_response_route for value in ("REVIEW_APPROVAL_FAILED", "REASONING_FAILED", "VOICE_GENERATION_FAILED", "AUDIO_RESPONSE_INVALID", "RESPONSE_PACKAGING_FAILED"))
    assert "Controlled local response failed; no automatic retry" not in review_response_route
    for category, message in broker.REVIEW_FAILURES.items():
        failure = json.loads(broker.review_failure_payload(category))
        assert failure == {"error": message, "failureCategory": category}
    log_block = server_source.split("def log_message", 1)[1].split("def _security_headers", 1)[0]
    assert all(value not in log_block for value in ("error", "stdout", "stderr", "exception", "transcript", "audio"))
    assert ptt_source.count("enumerateDevices()") == 1
    assert ptt_source.count("getUserMedia(") == 1
    assert "deviceId:{exact:requestedId}" in ptt_source
    assert all(value in ptt_source for value in ("Default - ", "Communications - ", "(BT)", "Hands-Free", "MAX_MS=15000"))
    assert all(value in ptt_source for value in ("event.isTrusted", 'event.pointerType==="mouse"', "event.isPrimary===true", "event.buttons!==1"))
    assert all(value in ptt_source for value in ("pointerup", "pointercancel", "lostpointercapture", "blur", "visibilitychange", "pagehide"))
    assert all(value not in ptt_source for value in ("navigator.clipboard", "localStorage", "sessionStorage", "WebSocket", "EventSource", "/api/speak", "Hermes"))
    assert "ptt-transcript" in ptt_source and "api/stt/transcribe" in ptt_source
    assert 'microphone=(self)' in html_source and "ptt-controller.js" in html_source
    assert '<textarea id="ptt-transcript"' in html_source and 'maxlength="800"' in html_source
    assert all(value in html_source for value in ("ORIGINAL LOCAL TRANSCRIPT", "SEND EDITED TEXT &amp; RESPOND", "DISCARD", "CANCEL MAEVE RESPONSE"))
    assert html_source.count('id="ptt-response"') == 1
    assert all(value in html_source for value in ('MAEVE RESPONSE — EXACT BROKER TEXT', 'role="status"', 'aria-live="polite"', 'aria-atomic="true"'))
    assert all(value in css_source for value in ("#ptt-original-transcript", "#ptt-transcript:focus-visible", "#ptt-cancel-response:not(:disabled)"))
    assert all(value in css_source for value in (".review-response", "#ptt-response", "white-space:pre-wrap"))
    assert all(value in ptt_source for value in ("AWAITING_APPROVAL", "EDITED APPROVAL CONSUMED", "pendingTranscriptId", "decisionConsumed", "approveAndRespond(pendingTranscriptId,approvedText)"))
    assert 'transcript.addEventListener("input",updateSendState)' in ptt_source
    assert 'approve.addEventListener("click",sendDecision)' in ptt_source and 'discard.addEventListener("click",discardDecision)' in ptt_source
    send_block = ptt_source.split("async function sendDecision", 1)[1].split("async function discardDecision", 1)[0]
    assert send_block.index("decisionConsumed=true") < send_block.index("await config.approveAndRespond")
    assert "apiFetch" not in send_block and "approvedText=transcript.value.trim()" in send_block
    send_failure_block = send_block.split("catch(error)", 1)[1]
    assert "clearReview()" not in send_failure_block
    assert "APPROVED TRANSCRIPT RETAINED IN MEMORY" in send_failure_block
    discard_block = ptt_source.split("async function discardDecision", 1)[1].split("if(physicalMode)", 1)[0]
    assert "approveAndRespond" not in discard_block and "config.discardTranscript(pendingTranscriptId)" in discard_block
    assert runtime_source.count("apiFetch(\"/api/speak\"") == 1
    assert "MAEVE_PTT_CONTROLLER.create" in runtime_source and "X-Maeve-Token" in runtime_source
    assert runtime_source.count('apiFetch("/api/response/approve"') == 1
    assert runtime_source.count('apiFetch("/api/response/playback-complete"') == 1
    assert runtime_source.count('apiFetch("/api/response/approve"') == 1 and runtime_source.count('apiFetch("/api/response/cancel"') == 2
    assert "APPROVED_RESPONSE" not in runtime_source and "approve-edited-transcript-and-respond" in runtime_source
    assert 'JSON.stringify({action:"approve-edited-transcript-and-respond",runtimeVersion:RUNTIME_VERSION,transcriptId,approvedText})' in runtime_source
    assert runtime_source.count("function publishReviewResponse(") == 1 and runtime_source.count("publishReviewResponse(responseId,result.text)") == 1
    publish_block = runtime_source.split("function publishReviewResponse", 1)[1].split("function updateMotionState", 1)[0]
    assert all(value in publish_block for value in ("activeReviewResponse?.responseId===responseId", "activeReviewResponse.text!==text", "return false", "Object.freeze({responseId,text})", "reviewResponse.textContent=text"))
    assert all(value not in publish_block for value in ("innerHTML", "append", "localStorage", "sessionStorage", "indexedDB", "document.cookie"))
    approve_block = runtime_source.split("async function approveAndRespond", 1)[1].split("async function discardTranscript", 1)[0]
    assert approve_block.index("publishReviewResponse(responseId,result.text)") < approve_block.index('playValidatedAudio(result.audioUrl,result.audio,"stage13-response",responseId)')
    assert approve_block.count('apiFetch("/api/response/approve"') == 1
    assert all(value in server_source for value in ("response_text = REASONER.reason(approved_transcript, [])", "VOICE.generate_response(response_text, response_id=response_id, require_stt=False)", '"text": response_text', '"responseId": response_id'))
    review_response_route = server_source.split('if path == "/api/response/approve":', 1)[1].split('if path == "/api/response/discard":', 1)[0]
    assert "STT.consume_approval" in review_response_route and "require_stt=False" in review_response_route
    assert review_response_route.index("STT.consume_approval") < review_response_route.index("require_stt=False")
    finish_block = runtime_source.split("async function finishPlayback", 1)[1].split("async function playValidatedAudio", 1)[0]
    cancel_block = runtime_source.split("async function cancelReviewPlayback", 1)[1].split("async function approveAndRespond", 1)[0]
    ready_block = runtime_source.split("function setState", 1)[1].split("function setPttState", 1)[0]
    assert all("reviewResponse" not in block and "activeReviewResponse" not in block for block in (finish_block, cancel_block, ready_block))
    assert 'window.addEventListener("pagehide",()=>{activeReviewResponse=null;reviewResponse.textContent="";' in runtime_source
    assert all(value not in runtime_source for value in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"))
    assert all(value in runtime_source for value in ("cancelReviewPlayback", 'reviewCancelButton.disabled=kind!=="stage13-response"', "ensureMicrophoneClosed", "activePlayback=null"))
    assert all(value in server_source for value in ("/api/response/approve", "/api/response/discard", "/api/response/cancel", "/api/response/playback-complete", "/api/audio/stage11.wav", "response_audio"))
    assert "approve-edited-transcript-and-respond" in server_source and "STT.consume_approval" in server_source
    assert server_source.index("STT.consume_approval") < server_source.index("REASONER.reason(approved_transcript")
    assert all(value in server_source for value in ("transcriptId", "approvedText", "responseId", "originalSha256", "approvedSha256", "ALREADY_CANCELLED"))
    assert "GPU.owner != \"NONE\"" in server_source and "GPU.owner != \"QWEN\"" in server_source
    assert "base64.b64decode" in server_source and "response_audio = None" in server_source
    assert all(value in qwen_source for value in ("0.5.0-stage13", "MAX_TEXT_CHARS = 360", "CANONICAL MAEVE LOCAL VOICE — COWBOY APPROVED", "audioBase64", 'storage": "memory-only"'))
    assert "OUTPUT =" not in qwen_source and "sf.write(output" in qwen_source
    assert "subprocess" not in qwen_source and "wsl.exe" not in qwen_source
    assert all(value not in qwen_source for value in ("http://", "https://", "requests.", "urllib", "socket."))
    assert all(value in worker_source for value in ("local_files_only=True", 'device="cuda"', 'compute_type="float16"', 'language="en"', "beam_size=1"))
    assert worker_source.count("WhisperModel(") == 1 and worker_source.count("model.transcribe(") == 2
    assert all(value in worker_source for value in ("warmupCalls", "last_job_id + 1", "transcriptReleasedAfterWrite", 'request["type"] == "shutdown"'))

    conversation_source = (ROOT / "ui" / "scripts" / "conversation-controller.js").read_text(encoding="utf-8")
    assert all(value in server_source for value in ("/api/conversation/start", "/api/conversation/turn", "/api/conversation/mute", "/api/conversation/end"))
    assert all(value in conversation_source for value in ("SILENCE_PROMPT_MS=30000", "SILENCE_GRACE_MS=15000", "SILENCE_MS=2200", "PRE_ROLL_MS=400", "VOICE_RMS=.035"))
    assert conversation_source.count("getUserMedia(") == 1 and "deviceId:{exact:deviceId}" in conversation_source
    assert all(value in conversation_source for value in ("closeMic()", "MUTED", "AUTO_CONTINUE", "visibilitychange", "pagehide", "conversation-cancel", "cleanupPromise"))
    assert "publishReviewResponse" not in conversation_source and "ptt-response" not in conversation_source
    print("STAGE13_REVIEW_RESPONSE_DISPLAY_STATIC_QA=PASS listeners=0 browser=0 wsl=0 microphone=0 models=0 requests=0")


if __name__ == "__main__":
    main()
