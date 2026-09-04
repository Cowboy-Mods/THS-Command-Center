"""Focused one-click Windows launcher regression tests; no runtime services."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_PATH = ROOT / "scripts" / "start-windows.py"
CMD_PATH = ROOT / "START MAEVE.cmd"
SPEC = importlib.util.spec_from_file_location("maeve_start_windows_regression", LAUNCHER_PATH)
assert SPEC and SPEC.loader
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)


class LauncherRegressionTests(unittest.TestCase):
    def test_approved_python_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            approved = Path(directory) / "python.exe"
            approved.touch()
            with patch.object(LAUNCHER, "PYTHON_EXE", approved), patch.object(
                LAUNCHER.sys, "executable", str(approved)
            ), patch.object(LAUNCHER.sys, "version_info", (3, 11, 15)):
                LAUNCHER.verify_python_runtime()

    def test_unrelated_virtual_environment_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            approved = Path(directory) / "approved-python.exe"
            unrelated = Path(directory) / "unrelated-python.exe"
            approved.touch()
            unrelated.touch()
            with patch.object(LAUNCHER, "PYTHON_EXE", approved), patch.object(
                LAUNCHER.sys, "executable", str(unrelated)
            ):
                with self.assertRaisesRegex(RuntimeError, r"START MAEVE\.cmd"):
                    LAUNCHER.verify_python_runtime()

    def test_wrong_python_version_is_rejected(self) -> None:
        fake_version = type("Version", (), {"__getitem__": lambda self, key: (3, 10, 0)[key]})()
        with tempfile.TemporaryDirectory() as directory:
            approved = Path(directory) / "python.exe"
            approved.touch()
            with patch.object(LAUNCHER, "PYTHON_EXE", approved), patch.object(
                LAUNCHER.sys, "executable", str(approved)
            ), patch.object(LAUNCHER.sys, "version_info", fake_version):
                with self.assertRaisesRegex(RuntimeError, "Unapproved Python runtime"):
                    LAUNCHER.verify_python_runtime()

    def test_cmd_uses_only_the_verified_runtime_and_browser_mode(self) -> None:
        source = CMD_PATH.read_text(encoding="utf-8")
        self.assertIn("if not defined MAEVE_PYTHON", source)
        self.assertIn('"%MAEVE_PYTHON%" -B "%MAEVE_LAUNCHER%" --open-browser', source)
        self.assertIn("--voice-provider elevenlabs", source)
        self.assertIn('cd /d "%MAEVE_ROOT%"', source)
        self.assertIn("No automatic retry was attempted", source)
        self.assertNotIn("powershell", source.casefold())
        self.assertNotIn("start ms-windows-store:", source.casefold())
        self.assertEqual(source.count('"%MAEVE_PYTHON%" -B'), 1)


if __name__ == "__main__":
    unittest.main()
