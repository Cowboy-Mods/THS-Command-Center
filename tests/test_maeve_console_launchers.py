import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MaeveConsoleLauncherTests(unittest.TestCase):
    def test_launchers_are_loopback_only_and_project_specific(self):
        script = (ROOT / "scripts" / "maeve-console.ps1").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1", script)
        self.assertIn("48176", script)
        self.assertIn("maeve_console.py", script)
        self.assertIn("maeve-console.stop", script)
        self.assertIn("maeve_farm_manager_bridge.py", script)
        self.assertIn("--remote-debugging-address=127.0.0.1", script)
        self.assertIn("--remote-debugging-port=", script)
        self.assertIn("control", (ROOT / "scripts" / "maeve_farm_manager_bridge.py").read_text(encoding="utf-8"))
        self.assertIn("Get-NetTCPConnection", script)
        self.assertNotIn("0.0.0.0", script)
        self.assertNotIn("taskkill /IM", script)


if __name__ == "__main__":
    unittest.main()
