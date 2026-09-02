from __future__ import annotations

from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "broker"))
from windows_playback import MemoryWavPlayback, PlaybackFailure, synthetic_tone_wav


calls = []
def immediate(sound, flags): calls.append((sound is None, flags))
p = MemoryWavPlayback(immediate)
tone = synthetic_tone_wav(0.1)
p.start(tone)
assert p.wait(1) == "COMPLETED" and p.start_count == 1 and len(calls) == 1 and not p.audio_retained()
try: p.start(b"not-wave")
except Exception: pass
else: raise AssertionError("invalid WAV accepted")
assert len(calls) == 1

gate = threading.Event()
def blocking(sound, flags):
    calls.append((sound is None, flags))
    if sound is not None: gate.wait(1)
    else: gate.set()
p2 = MemoryWavPlayback(blocking); p2.start(tone)
assert p2.cancel() == "CANCEL_REQUESTED"
assert p2.wait(1) == "CANCELED"
assert p2.cancel() == "ALREADY_CANCELED"
assert not p2.audio_retained() and p2.start_count == 1

source=(Path(__file__).resolve().parent.parent / "broker" / "windows_playback.py").read_text(encoding="utf-8")
harness=(Path(__file__).resolve().parent.parent / "scripts" / "test-memory-playback.py").read_text(encoding="utf-8")
assert all(value not in source+harness for value in ("ElevenLabsProvider","credential_read","urllib","requests.","subprocess","shell=True","powershell","cmd.exe","tempfile","NamedTemporaryFile"))
assert "SND_SYNC" not in source+harness and "SND_MEMORY" in source
print("WINDOWS_MEMORY_PLAYBACK_STATIC_QA=PASS starts=1 cancel=PASS retry=0 provider=0 disk_audio=0")
