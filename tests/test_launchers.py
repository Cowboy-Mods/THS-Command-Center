import unittest
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PermanentDashboardLauncherTests(unittest.TestCase):
    def test_serve_refuses_an_implicit_database(self):
        result = subprocess.run(
            [sys.executable, "-m", "inventory.cli", "serve"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--database is required for serve", result.stderr)

    def test_controlled_onboarding_refuses_an_implicit_database(self):
        result = subprocess.run(
            [sys.executable, "-m", "inventory.cli", "ams-onboard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--database is required for ams-onboard", result.stderr)

    def test_cmd_wrappers_are_checkout_relative(self):
        for filename, action in (
            ("Start THS Dashboard.cmd", "start"),
            ("Stop THS Dashboard.cmd", "stop"),
        ):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("%~dp0scripts\\ths-dashboard.ps1", text)
            self.assertIn(f"-Action {action}", text)
            self.assertIn(
                "%USERPROFILE%\\Documents\\THS-Command-Center-Data\\inventory.sqlite3",
                text,
            )
            self.assertIn('-DatabasePath "%THS_DATABASE%"', text)
            self.assertNotIn("\\Documents\\Codex\\", text)

    def test_powershell_launcher_derives_project_and_validates_process(self):
        text = (ROOT / "scripts" / "ths-dashboard.ps1").read_text(encoding="utf-8")
        for required in (
            "Split-Path -Parent $PSScriptRoot",
            "StartTimeUtcFileTime",
            "ExecutablePath",
            "ProjectPath",
            "DatabasePath",
            "ApplicationPath",
            "Get-VerifiedTHSProcess",
            "Get-CimInstance Win32_Process",
            "$commandLine.Contains($bootstrapPath)",
            '$commandLine.Contains("--database $databasePath")',
            '$commandLine.Contains("serve --host $expectedHost --port $expectedPort")',
            "$ownsExpectedListener",
            "Stop-Process -Id $process.Id",
            '"serve", "--host", "127.0.0.1", "--port", "8787"',
            "-I $bootstrapPath --database $databasePath migrate",
            "ths_dashboard_bootstrap.py",
            "port 8787 is already owned by process",
            "Where-Object { $_.OwningProcess -eq $server.Id }",
        ):
            self.assertIn(required, text)
        self.assertNotIn("-m inventory.cli", text)
        self.assertNotIn("\\Documents\\Codex\\", text)
        self.assertNotIn('Join-Path $projectPath "var"', text)

    def test_isolated_bootstrap_pins_inventory_to_this_checkout(self):
        text = (ROOT / "scripts" / "ths_dashboard_bootstrap.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "Path(__file__).resolve().parents[1]",
            "sys.path.insert(0, str(project_root))",
            "loaded_application != expected_application",
            "THS launcher safety check failed",
            "THS application path:",
            "from inventory.cli import main",
        ):
            self.assertIn(required, text)

    def test_launcher_supports_explicit_and_discovered_python(self):
        text = (ROOT / "scripts" / "ths-dashboard.ps1").read_text(encoding="utf-8")
        self.assertIn("$env:THS_PYTHON", text)
        self.assertIn('Get-Command "py.exe"', text)
        self.assertIn("print(sys.executable)", text)
        self.assertIn('Get-Command "python.exe"', text)
        self.assertIn("$env:USERPROFILE", text)

    def test_launcher_rejects_duplicate_or_occupied_production_port(self):
        text = (ROOT / "scripts" / "ths-dashboard.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-NetTCPConnection -LocalPort 8787 -State Listen", text)
        self.assertIn("THS Dashboard is already running as process", text)
        self.assertIn("port 8787 is already owned by process", text)

    def test_stale_marker_and_pid_reuse_are_handled_safely(self):
        text = (ROOT / "scripts" / "ths-dashboard.ps1").read_text(encoding="utf-8")
        self.assertIn("StartTimeUtcFileTime", text)
        self.assertIn("$sameStart", text)
        self.assertIn("Remove-StaleTHSRecord", text)
        self.assertIn("Remove-Item -LiteralPath $pidFile -Force", text)

    def test_stop_refuses_wrong_database_or_unrelated_process(self):
        text = (ROOT / "scripts" / "ths-dashboard.ps1").read_text(encoding="utf-8")
        self.assertIn("$sameDatabase", text)
        self.assertIn("$sameCommandLine", text)
        self.assertIn("$ownsExpectedListener", text)
        self.assertIn("Safety check failed: PID, command line, database path", text)
        self.assertLess(
            text.index("Get-VerifiedTHSProcess $record"),
            text.index("Stop-Process -Id $process.Id"),
        )

    def test_development_launcher_is_explicit_and_separated(self):
        text = (ROOT / "scripts" / "ths-dashboard-development.ps1").read_text(
            encoding="utf-8"
        )
        for required in (
            "[Parameter(Mandatory = $true)]",
            "$developmentPort = 8788",
            "Development launcher refuses the production database",
            "Explicit development database was not found",
            "THS DEVELOPMENT",
            "--database $databasePath serve --host 127.0.0.1 --port $developmentPort",
        ):
            self.assertIn(required, text)
        self.assertNotIn("--port 8787", text)


if __name__ == "__main__":
    unittest.main()
