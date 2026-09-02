"""Cancelable Windows default-device playback for validated in-memory WAV bytes."""

from __future__ import annotations

import io
import threading
import winsound
import wave

from voice_provider import validate_wav


class PlaybackFailure(RuntimeError):
    pass


class MemoryWavPlayback:
    def __init__(self, sound_api=winsound.PlaySound) -> None:
        self._sound_api = sound_api
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._audio: bytes | None = None
        self._cancel_requested = False
        self.state = "IDLE"
        self.start_count = 0

    def start(self, audio: bytes) -> None:
        evidence = validate_wav(audio)
        if evidence["sampleRate"] != 24000 or evidence["channels"] != 1:
            raise PlaybackFailure("PLAYBACK_AUDIO_REJECTED")
        with self._lock:
            if self._thread is not None or self.state == "PLAYING":
                raise PlaybackFailure("DUPLICATE_PLAYBACK_REJECTED")
            self._audio = bytes(audio)
            self._cancel_requested = False
            self.state = "PLAYING"
            self.start_count += 1
            self._thread = threading.Thread(target=self._run, name="maeve-memory-wav-playback", daemon=False)
            self._thread.start()

    def _run(self) -> None:
        try:
            self._sound_api(self._audio, winsound.SND_MEMORY)
            with self._lock:
                self.state = "CANCELED" if self._cancel_requested else "COMPLETED"
        except Exception:
            with self._lock:
                self.state = "FAILED"
        finally:
            with self._lock:
                self._audio = None
                self._thread = None

    def wait(self, timeout: float) -> str:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                self.cancel()
                raise PlaybackFailure("PLAYBACK_TIMEOUT")
        return self.state

    def cancel(self) -> str:
        with self._lock:
            if self.state == "CANCELED": return "ALREADY_CANCELED"
            if self.state != "PLAYING": return "NO_ACTIVE_PLAYBACK"
            self._cancel_requested = True
        self._sound_api(None, 0)
        return "CANCEL_REQUESTED"

    def audio_retained(self) -> bool:
        with self._lock: return self._audio is not None


def synthetic_tone_wav(duration_seconds: float = 0.45, frequency_hz: float = 523.25) -> bytes:
    if not (0.1 <= duration_seconds <= 2.0 and 100.0 <= frequency_hz <= 2000.0):
        raise PlaybackFailure("SYNTHETIC_TONE_BOUNDS_REJECTED")
    import math
    import struct
    sample_rate = 24000
    frames = bytearray()
    for index in range(int(sample_rate * duration_seconds)):
        envelope = min(1.0, index / 480, (int(sample_rate * duration_seconds) - index) / 480)
        value = int(9000 * max(0.0, envelope) * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
        frames.extend(struct.pack("<h", value))
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(sample_rate); handle.writeframes(frames)
    return output.getvalue()
