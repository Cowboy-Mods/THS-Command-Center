import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from inventory.credentials import (
    CredentialStoreError,
    credential_status,
    default_p1s_credential_path,
    load_p1s_access_code,
    store_p1s_access_code,
)
from inventory.telemetry import FEATURE_FLAG, HOST_VARIABLE, SERIAL_VARIABLE, P1STelemetryConfig


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows DPAPI test")
class P1SCredentialProtectionTests(unittest.TestCase):
    def test_fake_secret_is_dpapi_protected_and_round_trips_for_current_user(self):
        fake = "FAKE-P1S-CREDENTIAL-ONLY"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "p1s.dpapi"
            status = store_p1s_access_code(fake, path)
            self.assertTrue(status.present)
            self.assertTrue(status.protected_for_current_user)
            self.assertEqual(load_p1s_access_code(path), fake)
            self.assertNotIn(fake.encode(), path.read_bytes())
            self.assertNotIn(fake, json.dumps(status.safe_summary()))

    def test_wrong_windows_user_or_corrupt_blob_is_reported_without_contents(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "p1s.dpapi"
            path.write_bytes(b"synthetic-corrupt-blob")
            status = credential_status(path)
            self.assertTrue(status.present)
            self.assertFalse(status.protected_for_current_user)
            with self.assertRaisesRegex(CredentialStoreError, "could not decrypt"):
                load_p1s_access_code(path)

    def test_default_store_is_outside_repository_and_git_ignored(self):
        path = default_p1s_credential_path({"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"})
        self.assertNotIn(str(ROOT).casefold(), str(path).casefold())
        ignores = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*.dpapi", ignores)
        self.assertIn("/.local-secrets/", ignores)

    def test_cli_accepts_no_credential_command_line_argument(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "p1s_credential.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("access-code", result.stdout)
        self.assertNotIn("password", result.stdout.casefold())

    def test_telemetry_configuration_reads_fake_secret_only_from_dpapi_store(self):
        fake = "FAKE-P1S-CREDENTIAL-ONLY"
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "p1s.dpapi"
            store_p1s_access_code(fake, path)
            config = P1STelemetryConfig.from_protected_store(
                {
                    FEATURE_FLAG: "true",
                    HOST_VARIABLE: "192.168.4.99",
                    SERIAL_VARIABLE: "SYNTHETIC-SERIAL",
                },
                path,
            )
            self.assertEqual(config.access_code, fake)
            self.assertNotIn(fake, repr(config))
            self.assertNotIn(fake, json.dumps(config.safe_summary()))


if __name__ == "__main__":
    unittest.main()
