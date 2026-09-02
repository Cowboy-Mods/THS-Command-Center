"""Persistent, offline Maeve STT worker using a bounded JSON-lines protocol."""
from __future__ import annotations
import base64, gc, io, json, os, sys, time, wave
from faster_whisper import WhisperModel

MODEL_PATH = os.environ.get("MAEVE_STT_MODEL_PATH", "")
MAX_AUDIO_BYTES = 4 * 1024 * 1024

def emit(value: dict[str, object]) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)

def silence_fixture() -> io.BytesIO:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 4000)
    output.seek(0)
    return output

def valid_session(value: object) -> bool:
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)

def main() -> None:
    if not MODEL_PATH.startswith("/"):
        raise RuntimeError("STT model path is not configured")
    started = time.monotonic()
    model = WhisperModel(MODEL_PATH, device="cuda", device_index=0, compute_type="float16",
                         cpu_threads=0, num_workers=1, local_files_only=True)
    model_load_seconds = time.monotonic() - started
    warmup = silence_fixture(); started = time.monotonic()
    warm_segments, _warm_info = model.transcribe(warmup, language="en", beam_size=1)
    list(warm_segments); warmup.close(); del warm_segments, _warm_info; gc.collect()
    emit({"type":"ready", "status":"PASS", "workerPid":os.getpid(), "constructorCalls":1,
          "warmupCalls":1, "modelLoadSeconds":model_load_seconds,
          "warmupSeconds":time.monotonic()-started,
          "networkRoutesEmpty":not open("/proc/net/route", encoding="utf-8").read().strip()})
    session_id: str | None = None
    last_job_id = 0
    while True:
        line = sys.stdin.buffer.readline(MAX_AUDIO_BYTES * 2)
        if not line: break
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or not isinstance(request.get("type"), str): raise ValueError("protocol schema rejected")
            if request["type"] == "shutdown":
                emit({"type":"stopped", "status":"PASS", "workerPid":os.getpid()}); break
            if request["type"] != "transcribe": raise ValueError("protocol type rejected")
            candidate_session, job_id = request.get("sessionId"), request.get("jobId")
            if not valid_session(candidate_session) or not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1:
                raise ValueError("identity rejected")
            if session_id is None: session_id = candidate_session
            if candidate_session != session_id or job_id != last_job_id + 1:
                raise ValueError("stale duplicate mismatched or replayed identity rejected")
            encoded = request.get("audioBase64")
            if not isinstance(encoded, str) or len(encoded) > ((MAX_AUDIO_BYTES + 2) // 3) * 4: raise ValueError("audio boundary rejected")
            audio = base64.b64decode(encoded, validate=True)
            if not audio or len(audio) > MAX_AUDIO_BYTES: raise ValueError("audio boundary rejected")
            last_job_id = job_id; buffer = io.BytesIO(audio); started = time.monotonic()
            segments, info = model.transcribe(buffer, language="en", beam_size=1)
            text = "".join(segment.text for segment in segments).strip(); elapsed = time.monotonic()-started
            buffer.close(); audio = b""; encoded = ""; del segments, info; gc.collect()
            emit({"type":"transcribed", "status":"PASS", "sessionId":session_id, "jobId":job_id,
                  "text":text, "transcribeCalls":1, "transcribeSeconds":elapsed,
                  "audioReleased":True, "transcriptReleasedAfterWrite":True})
            text = ""
        except Exception as exc:
            emit({"type":"rejected", "status":"FAIL", "error":type(exc).__name__})
    del model; gc.collect()

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        emit({"type":"fatal", "status":"FAIL", "error":type(exc).__name__}); raise
