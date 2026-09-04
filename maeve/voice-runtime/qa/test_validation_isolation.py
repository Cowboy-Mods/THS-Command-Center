"""Focused synthetic credential and ledger isolation regression tests."""
from pathlib import Path
import sys, unittest
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'broker'))
import server as broker
import voice_provider
from validation_isolation import isolated_broker

class CredentialIsolationTests(unittest.TestCase):
    def test_status_uses_only_in_memory_fake(self):
        with isolated_broker(broker) as (providers,directory):
            worker=broker.VoiceWorker('ELEVENLABS')
            self.assertTrue(worker.health()['voiceProvider']['available'])
            self.assertTrue(all(p.credential_reader is not voice_provider.credential_read for p in providers))
    def test_native_credential_entry_points_fail_closed(self):
        with isolated_broker(broker):
            for name in ('credential_read','credential_write','credential_remove','_credential_api'):
                with self.assertRaisesRegex(AssertionError,'UNEXPECTED_PRIVATE_STATE_ACCESS'):
                    getattr(voice_provider,name)()

class LedgerIsolationTests(unittest.TestCase):
    def test_counts_round_trip_in_temporary_directory(self):
        with isolated_broker(broker) as (providers,directory):
            worker=broker.VoiceWorker('ELEVENLABS')
            ledger=worker.cloud.ledger
            self.assertTrue(ledger.path.is_relative_to(directory))
            self.assertFalse(directory.is_relative_to(ROOT))
            ledger._write({'month':ledger._month(),'requests':3,'characters':12,'successful':1,'failed':1,'canceled':1})
            self.assertEqual(ledger.status()['requests'],3)
            self.assertNotIn(worker.cloud.credential_reader(),ledger.path.read_text())
        self.assertFalse(directory.exists())
    def test_default_ledger_fails_closed(self):
        with isolated_broker(broker):
            with self.assertRaisesRegex(AssertionError,'UNEXPECTED_PRIVATE_STATE_ACCESS'):
                voice_provider.default_ledger()
