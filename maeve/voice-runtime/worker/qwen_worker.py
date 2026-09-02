#!/usr/bin/env python3
"""Offline one-response Qwen Candidate B worker for bounded Maeve text."""
from __future__ import annotations
import base64, gc, hashlib, io, json, math, os, random, sys, time, wave
from pathlib import Path

# Reserve the original stdout pipe exclusively for one-line JSON protocol
# frames, then redirect fd 1 before importing any model/library code.  Python,
# native-library, warning and progress output can no longer enter the protocol.
_PROTOCOL_FD = os.dup(sys.stdout.fileno())
os.set_inheritable(_PROTOCOL_FD, False)
_NULL_STDOUT_FD = os.open(os.devnull, os.O_WRONLY)
try:
    os.dup2(_NULL_STDOUT_FD, sys.stdout.fileno(), inheritable=False)
finally:
    os.close(_NULL_STDOUT_FD)

import numpy as np
import soundfile as sf
import torch
from safetensors import safe_open
from qwen_tts import Qwen3TTSModel, VoiceClonePromptItem

RUNTIME_VERSION = "0.5.0-stage13"
MAX_TEXT_CHARS = 360
SEED = 20260837
MODEL = Path(os.environ.get("MAEVE_QWEN_MODEL_PATH", "UNCONFIGURED_QWEN_MODEL"))
IDENTITY = Path(os.environ.get("MAEVE_QWEN_IDENTITY_PATH", "UNCONFIGURED_QWEN_IDENTITY"))
IDENTITY_JSON_SHA = "5827e2e9dd7d8618bd80f9569f5e8472c5138c9caaa8cef3731d3257f9e548e1"
PROMPT_SHA = "41aae9981f6c05333dcffd1569df84a4c1cf6ebef0103abf4f6dacec4e75b24a"

def send(value):
    if not isinstance(value, dict): raise TypeError("protocol object required")
    payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    view = memoryview(payload)
    while view:
        written = os.write(_PROTOCOL_FD, view)
        if written <= 0: raise BrokenPipeError("protocol channel closed")
        view = view[written:]
def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()
def sha256_tensor(tensor): return hashlib.sha256(tensor.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()).hexdigest()
def strict_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value: raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value
def gpu(): return {"allocatedBytes": torch.cuda.memory_allocated(), "reservedBytes": torch.cuda.memory_reserved()}
def load_identity():
    metadata_path, prompt_path = IDENTITY / "identity.json", IDENTITY / "voice-prompt.safetensors"
    if sha256_file(metadata_path) != IDENTITY_JSON_SHA or sha256_file(prompt_path) != PROMPT_SHA: raise RuntimeError("canonical identity file mismatch")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)
    if metadata.get("status") != "CANONICAL MAEVE LOCAL VOICE — COWBOY APPROVED" or metadata.get("realPersonClone") is not False: raise RuntimeError("canonical identity approval mismatch")
    expected = {item["name"]: item for item in metadata["voicePrompt"]["tensors"]}
    with safe_open(prompt_path, framework="pt", device="cpu") as handle:
        if sorted(handle.keys()) != sorted(expected): raise RuntimeError("canonical tensor inventory mismatch")
        tensors = {name: handle.get_tensor(name) for name in handle.keys()}
    for name, item in expected.items():
        tensor = tensors[name]
        if list(tensor.shape) != item["shape"] or str(tensor.dtype) != item["dtype"] or sha256_tensor(tensor) != item["sha256"]: raise RuntimeError(f"canonical tensor mismatch: {name}")
    prompt = [VoiceClonePromptItem(ref_code=tensors["item0.ref_code"], ref_spk_embedding=tensors["item0.ref_spk_embedding"], x_vector_only_mode=False, icl_mode=True, ref_text=metadata["reference"]["transcript"])]
    return prompt, {"identityJsonSha256": IDENTITY_JSON_SHA, "promptSha256": PROMPT_SHA, "tensors": expected}
def validate_wav(source, sample_rate):
    if source.size == 0 or sample_rate != 24000 or not np.isfinite(source).all(): raise RuntimeError("invalid generated waveform")
    output = io.BytesIO(); sf.write(output, source, sample_rate, subtype="PCM_16", format="WAV"); wav_bytes = output.getvalue()
    with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
        channels, width, rate, frames, comp = handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes(), handle.getcomptype(); pcm = np.frombuffer(handle.readframes(frames), dtype="<i2")
    if channels != 1 or width != 2 or rate != 24000 or frames <= 0 or comp != "NONE": raise RuntimeError("WAV format validation failed")
    normalized = pcm.astype(np.float64) / 32768.0; peak = float(np.max(np.abs(normalized))); rms = float(np.sqrt(np.mean(np.square(normalized)))); clipped = int(np.count_nonzero((pcm == -32768) | (pcm == 32767)))
    if not math.isfinite(peak) or not math.isfinite(rms) or peak <= 0 or rms <= 0 or clipped: raise RuntimeError("WAV signal validation failed")
    return wav_bytes, {"bytes": len(wav_bytes), "sha256": hashlib.sha256(wav_bytes).hexdigest(), "format": "RIFF/WAVE PCM-16", "sampleRate": rate, "channels": channels, "frames": frames, "durationSeconds": frames / rate, "peak": peak, "rms": rms, "clippedSamples": clipped, "nan": int(np.isnan(source).sum()), "infinity": int(np.isinf(source).sum()), "storage": "memory-only"}
def main():
    random.seed(SEED); np.random.seed(SEED); torch.manual_seed(SEED); torch.cuda.manual_seed_all(SEED); torch.use_deterministic_algorithms(False); torch.backends.cudnn.deterministic = True; torch.backends.cudnn.benchmark = False
    prompt, identity = load_identity(); started = time.perf_counter()
    model = Qwen3TTSModel.from_pretrained(str(MODEL), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa", local_files_only=True, trust_remote_code=False, use_safetensors=True)
    send({"type": "ready", "runtimeVersion": RUNTIME_VERSION, "identity": identity, "modelLoadSeconds": time.perf_counter() - started, "gpuAfterLoad": gpu(), "referenceWavOpened": False, "referenceAudioEncoded": False, "networkNamespace": "unshare --net"})
    generated = False
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("type") == "shutdown": break
        text = request.get("text")
        if request.get("type") != "generate" or not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS or generated: send({"type": "error", "error": "unsupported or repeated request"}); continue
        text = " ".join(text.split()); generated = True; started = time.perf_counter()
        wavs, sample_rate = model.generate_voice_clone(text=text, language="English", voice_clone_prompt=prompt, non_streaming_mode=True, do_sample=True, top_k=50, top_p=1.0, temperature=0.9, repetition_penalty=1.05, subtalker_dosample=True, subtalker_top_k=50, subtalker_top_p=1.0, subtalker_temperature=0.9, max_new_tokens=480)
        if len(wavs) != 1: raise RuntimeError("unexpected waveform count")
        wav_bytes, audio = validate_wav(np.asarray(wavs[0], dtype=np.float32).reshape(-1), int(sample_rate))
        send({"type": "generated", "status": "PASS", "text": text, "seed": SEED, "generationSeconds": time.perf_counter() - started, "audio": audio, "audioBase64": base64.b64encode(wav_bytes).decode("ascii"), "gpuAfterGeneration": gpu(), "attempt": 1})
        wav_bytes = b""
    del model, prompt; gc.collect(); torch.cuda.empty_cache(); torch.cuda.ipc_collect(); return 0
if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc: send({"type": "error", "error": f"{type(exc).__name__}: {exc}"}); raise
