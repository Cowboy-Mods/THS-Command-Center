"""Pure guard tests: no child processes, credentials, ledgers, or network."""
import sys, unittest
from pathlib import Path
from subprocess_guard import effective_executable, ExecutableRejected

class SubprocessGuardTests(unittest.TestCase):
    def accepted(self,explicit,command):
        self.assertEqual(effective_executable(explicit,command,sys.executable),Path(sys.executable))
    def test_none_with_list(self): self.accepted(None,[sys.executable,'-c','pass'])
    def test_none_with_quoted_windows_string(self): self.accepted(None,'"'+sys.executable+'" -c "pass"')
    def test_explicit_allowed(self): self.accepted(sys.executable,['synthetic-argv-zero','-c','pass'])
    def test_pathlike_explicit(self): self.accepted(Path(sys.executable),[Path(sys.executable),'-c','pass'])
    def test_pathlike_command(self): self.accepted(None,[Path(sys.executable)])
    def test_prohibited_and_relative(self):
        for exe in ('cmd.exe',r'C:\Windows\System32\cmd.exe',r'C:\private\not-read.exe'):
            with self.assertRaises(ExecutableRejected): effective_executable(exe,[sys.executable],sys.executable)
    def test_malformed(self):
        for command in (None,[],(),'', '   ','"unfinished', [''],[None],[1],['x\0y'],b'bytes'):
            with self.assertRaises(ExecutableRejected): effective_executable(None,command,sys.executable)
    def test_explicit_does_not_hide_malformed(self):
        with self.assertRaises(ExecutableRejected): effective_executable(sys.executable,[],sys.executable)
    def test_shell_command_blocked(self):
        with self.assertRaises(ExecutableRejected): effective_executable(None,'cmd.exe /c anything',sys.executable)
