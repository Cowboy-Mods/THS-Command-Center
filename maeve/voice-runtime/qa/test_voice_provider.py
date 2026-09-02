from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "broker"))
from voice_provider import ELEVENLABS_SPEED, ElevenLabsProvider, ProviderFailure, UsageLedger, UsageLimits, validate_wav


class FakeResponse:
    status = 200
    headers = {"Content-Type": "application/octet-stream"}
    def __init__(self, payload: bytes): self.payload, self.offset, self.closed = payload, 0, False
    def read(self, size: int) -> bytes:
        result = self.payload[self.offset:self.offset + size]; self.offset += len(result); return result
    def close(self): self.closed = True


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []
        self.pcm = b"\x01\x00" * 2400
        def opener(request, timeout):
            self.calls.append((request, timeout))
            return FakeResponse(self.pcm)
        ledger = UsageLedger(Path(self.temp.name) / "usage.json", UsageLimits(monthly=2000, session=2000, warning=1600))
        self.provider = ElevenLabsProvider(ledger=ledger, opener=opener, credential_reader=lambda: "x" * 32)

    def tearDown(self): self.temp.cleanup()

    def test_exactly_one_identity_bound_request_and_audio(self):
        rid = "a" * 32
        result = self.provider.generate_response("Maeve online.", rid)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["provider"], "ELEVENLABS")
        audio = self.provider.take_audio(rid)
        self.assertEqual(validate_wav(audio)["sampleRate"], 24000)
        with self.assertRaises(ProviderFailure): self.provider.take_audio(rid)
        self.provider.complete(rid)
        with self.assertRaises(ProviderFailure): self.provider.generate_response("Maeve online.", rid)

    def test_explicit_supported_speed_is_the_only_voice_setting(self):
        rid = "9" * 32
        self.provider.generate_response("Maeve online.", rid)
        self.assertEqual(len(self.calls), 1)
        body = json.loads(self.calls[0][0].data.decode("utf-8"))
        self.assertEqual(ELEVENLABS_SPEED, 0.90)
        self.assertGreaterEqual(ELEVENLABS_SPEED, 0.7)
        self.assertLessEqual(ELEVENLABS_SPEED, 1.2)
        self.assertEqual(body["voice_settings"], {"speed": 0.90})
        self.assertEqual(body["model_id"], "eleven_flash_v2_5")
        self.assertNotIn("stability", body["voice_settings"])
        self.assertNotIn("similarity_boost", body["voice_settings"])
        self.assertNotIn("style", body["voice_settings"])
        self.assertNotIn("use_speaker_boost", body["voice_settings"])

    def test_cancel_invalidates_late_audio_without_retry(self):
        rid = "b" * 32
        self.provider.generate_response("Maeve online.", rid)
        self.assertEqual(self.provider.cancel(rid), "CANCELLED")
        self.assertEqual(self.provider.cancel(rid), "ALREADY_CANCELLED")
        with self.assertRaises(ProviderFailure): self.provider.take_audio(rid)
        self.assertEqual(len(self.calls), 1)

    def test_missing_key_and_usage_ceiling_block_before_contact(self):
        self.provider.credential_reader = lambda: None
        with self.assertRaises(ProviderFailure): self.provider.generate_response("Maeve online.", "c" * 32)
        self.assertEqual(self.calls, [])
        self.provider.credential_reader = lambda: "x" * 32
        with self.assertRaises(ProviderFailure): self.provider.generate_response("x" * 2001, "d" * 32)
        self.assertEqual(self.calls, [])

    def test_malformed_non_audio_and_oversized_fail_closed(self):
        self.provider.opener = lambda request, timeout: FakeResponse(b"odd")
        with self.assertRaises(ProviderFailure): self.provider.generate_response("Maeve online.", "e" * 32)
        self.provider.stop()
        self.provider.opener = lambda request, timeout: type("R", (), {"status":200,"headers":{"Content-Type":"text/plain"},"read":lambda s,n:b"","close":lambda s:None})()
        with self.assertRaises(ProviderFailure): self.provider.generate_response("Maeve online.", "f" * 32)

    def test_ledger_is_counts_only(self):
        rid = "1" * 32
        self.provider.generate_response("private canonical text", rid)
        raw = self.provider.ledger.path.read_text(encoding="utf-8")
        self.assertNotIn("private", raw)
        self.assertEqual(set(json.loads(raw)), {"month","requests","characters","successful","failed","canceled"})


if __name__ == "__main__": unittest.main()
