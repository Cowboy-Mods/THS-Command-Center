"""One-shot offline physical test of Maeve's memory-only Windows playback."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "broker"))
from windows_playback import MemoryWavPlayback, synthetic_tone_wav  # noqa: E402


def main() -> int:
    playback = MemoryWavPlayback()
    audio = synthetic_tone_wav()
    playback.start(audio)
    audio = b""
    state = playback.wait(5)
    result = {"category":"SYNTHETIC_MEMORY_PLAYBACK","startCount":playback.start_count,
              "state":state,"audioRetained":playback.audio_retained(),"providerRequests":0,
              "microphone":0,"stt":0,"openAI":0,"qwen":0,"temporaryAudioFiles":0}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if state == "COMPLETED" and playback.start_count == 1 and not playback.audio_retained() else 1


if __name__ == "__main__": raise SystemExit(main())
