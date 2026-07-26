import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PermanentDashboardLauncherTests(unittest.TestCase):
    def test_cmd_wrappers_are_checkout_relative(self):
        for filename, action in (
            ("Start THS Dashboard.cmd", "start"),
            ("Stop THS Dashboard.cmd", "stop"),
        ):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("%~dp0scripts\\ths-dashboard.ps1", text)
            self.assertIn(f"-Action {action}", text)
            self.assertNotIn("\\Documents\\Codex\\", text)

    def test_powershell_launcher_derives_project_and_validates_process(self):
        text = (ROOT / "scripts" / "ths-dashboard.ps1").read_text(encoding="utf-8")
        for required in (
            "Split-Path -Parent $PSScriptRoot",
            "inventory.cli migrate",
            '"inventory.cli", "serve"',
            "StartTimeUtcFileTime",
            "ExecutablePath",
            "ProjectPath",
            "Get-VerifiedTHSProcess",
            "Stop-Process -Id $process.Id",
        ):
            self.assertIn(required, text)
        self.assertNotIn("\\Documents\\Codex\\", text)

    def test_launcher_supports_explicit_and_discovered_python(self):
        text = (ROOT / "scripts" / "ths-dashboard.ps1").read_text(encoding="utf-8")
        self.assertIn("$env:THS_PYTHON", text)
        self.assertIn('Get-Command "py.exe"', text)
        self.assertIn("print(sys.executable)", text)
        self.assertIn('Get-Command "python.exe"', text)
        self.assertIn("$env:USERPROFILE", text)


if __name__ == "__main__":
    unittest.main()
