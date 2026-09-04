"""Offline ownership regressions; no real processes or native services."""
import inspect
import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from test_launcher import LAUNCHER
from test_close_control import broker


class LaunchOwnershipTests(unittest.TestCase):
    def test_stt_uses_this_copy(self):
        root = Path(broker.__file__).resolve().parent.parent
        w = root / "worker/stt_worker.py"
        broker.RUNTIME_CONFIG = {"stt_distribution":"Maeve-STT","stt_python":"/opt/maeve-stt/venv/bin/python",
            "stt_worker_path":"/mnt/"+w.drive[0].lower()+w.as_posix()[2:],"stt_model_path":"/srv/models/stt"}
        command = broker.SttService._command()
        worker = (Path(broker.__file__).resolve().parent.parent / 'worker/stt_worker.py').resolve()
        self.assertEqual(command[-1], '/mnt/' + worker.drive[0].lower() + worker.as_posix()[2:])
        self.assertTrue(worker.is_relative_to(Path(broker.__file__).resolve().parent.parent))
        self.assertEqual(worker, (Path(__file__).resolve().parent.parent/'worker/stt_worker.py').resolve())
        self.assertIn('--net', command)
        self.assertIn('HF_HUB_OFFLINE=1', command)
        self.assertIn('PYTHONDONTWRITEBYTECODE=1', command)
        self.assertEqual(command[-3:], ['/opt/maeve-stt/venv/bin/python', '-B',
                                      '/mnt/' + worker.drive[0].lower() + worker.as_posix()[2:]])
        self.assertEqual(command[:14], ['wsl.exe', '-d', 'Maeve-STT', '-u', 'root', '--', 'env',
                                      'PIP_NO_INDEX=1', 'PIP_DISABLE_PIP_VERSION_CHECK=1',
                                      'HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1',
                                      'HF_HUB_DISABLE_TELEMETRY=1', 'PYTHONDONTWRITEBYTECODE=1', 'CUDA_VISIBLE_DEVICES=0'])
        self.assertEqual(command[14], 'LD_LIBRARY_PATH=/opt/maeve-stt/venv/lib/python3.12/site-packages/nvidia/cublas/lib:/opt/maeve-stt/venv/lib/python3.12/site-packages/nvidia/cudnn/lib:/opt/maeve-stt/venv/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib')
        self.assertEqual(command[16:-3], ['unshare', '--net', 'runuser', '-u', 'maeve-stt', '--'])
        self.assertFalse(any(value in command for value in ('sh', 'bash', '-c', 'cmd.exe', 'powershell')))
        tree = ast.parse(inspect.getsource(broker))
        service = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SttService')
        start = next(node for node in service.body if isinstance(node, ast.FunctionDef) and node.name == 'start')
        calls = [node for node in ast.walk(start) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'Popen']
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.unparse(calls[0].args[0]), 'self._command()')
        self.assertFalse(any(kw.arg == 'shell' and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
                             for kw in calls[0].keywords))

    def test_profiles_unique_and_outside_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(LAUNCHER.tempfile, 'tempdir', directory):
                first = LAUNCHER.create_browser_profile()
                second = LAUNCHER.create_browser_profile()
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(directory).resolve())
            self.assertFalse(first.is_relative_to(LAUNCHER.RUNTIME_ROOT))

    def test_browser_uses_only_dedicated_profile(self):
        profile = Path(tempfile.gettempdir()) / 'maeve-close-owned-edge-synthetic'
        args = LAUNCHER.browser_arguments(profile, 'http://127.0.0.1:48177/', test_mode='no-voice')
        self.assertIn('--user-data-dir=' + str(profile), args)
        self.assertIn('--disable-background-networking', args)
        self.assertIn('--deny-permission-prompts', args)
        self.assertIn('--mute-audio', args)
        self.assertIn('--proxy-server=http://127.0.0.1:9', args)
        with self.assertRaises(RuntimeError):
            LAUNCHER.browser_arguments(profile, 'https://example.invalid/')

    def test_normal_mode_preserves_media_capability(self):
        profile = Path(tempfile.gettempdir()) / 'maeve-close-owned-edge-synthetic'
        normal = LAUNCHER.browser_arguments(profile, 'http://127.0.0.1:48177/')
        restricted = LAUNCHER.browser_arguments(profile, 'http://127.0.0.1:48177/', test_mode='no-voice')
        self.assertEqual(restricted[:len(normal)], normal)
        self.assertEqual(normal, [str(LAUNCHER.EDGE_EXE), '--user-data-dir='+str(profile),
                                 '--app=http://127.0.0.1:48177/', '--no-first-run',
                                 '--no-default-browser-check', '--disable-background-mode'])
        self.assertEqual(restricted[len(normal):], ['--disable-background-networking',
                         '--disable-sync', '--disable-extensions', '--disable-component-update',
                         '--disable-domain-reliability', '--disable-breakpad', '--disable-crash-reporter',
                         '--disable-default-apps', '--disable-client-side-phishing-detection',
                         '--disable-features=PreconnectToSearch,Prerender2,SpeculationRulesPrefetch,msEdgeSidebarV2,msStartupBoost',
                         '--no-pings', '--metrics-recording-only', '--deny-permission-prompts', '--mute-audio',
                         '--autoplay-policy=user-gesture-required', '--proxy-server=http://127.0.0.1:9',
                         '--proxy-bypass-list=127.0.0.1'])
        for args in (normal, restricted):
            self.assertFalse(any('host-resolver-rules' in value for value in args))
        self.assertNotIn('--test-mode', (LAUNCHER.RUNTIME_ROOT/'START MAEVE.cmd').read_text())

    def test_mode_selection_fails_closed(self):
        import contextlib, io
        with patch.object(LAUNCHER.sys, 'argv', ['launcher']):
            self.assertIsNone(LAUNCHER.parse_arguments().test_mode)
        with patch.object(LAUNCHER.sys, 'argv', ['launcher', '--test-mode', 'no-voice']):
            self.assertEqual(LAUNCHER.parse_arguments().test_mode, 'no-voice')
        for args in (['--test-mode'], ['--test-mode', 'normal'], ['--test-mode', ''],
                     ['--test-m', 'no-voice'], ['--test-mode', 'no-voice', '--test-mode', 'no-voice']):
            with patch.object(LAUNCHER.sys, 'argv', ['launcher', *args]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): LAUNCHER.parse_arguments()
        profile = Path(tempfile.gettempdir()) / 'maeve-close-owned-edge-synthetic'
        for value in ('', 'normal', True, 'NO-VOICE'):
            with self.assertRaises(RuntimeError):
                LAUNCHER.browser_arguments(profile, 'http://127.0.0.1:48177/', test_mode=value)

    def test_protected_handles_rejected_without_signal(self):
        children = LAUNCHER.OwnedChildren()
        for pid in (22504, 30708):
            process = Mock(pid=pid)
            with self.assertRaisesRegex(RuntimeError, 'unowned'):
                children.stop_exact(process, graceful_break=True)
            process.poll.assert_not_called()
            process.send_signal.assert_not_called()
            process.terminate.assert_not_called()
            process.kill.assert_not_called()

    def test_only_recorded_child_cleaned(self):
        children = LAUNCHER.OwnedChildren()
        process = Mock(pid=123456)
        process.poll.return_value = None
        children._children[process.pid] = process
        self.assertEqual(children.stop_all_exact(), [(123456, 'graceful-break')])
        process.send_signal.assert_called_once()
        process.terminate.assert_not_called()
        self.assertFalse(children._children)

    def test_ports_are_checks_not_termination(self):
        self.assertEqual((LAUNCHER.PORT, LAUNCHER.RESERVED_PORT), (48177, 48178))
        source = inspect.getsource(LAUNCHER.ensure_closed)
        self.assertNotIn('terminate', source)
        for module in (LAUNCHER, broker):
            source = inspect.getsource(module).lower()
            for prohibited in ('taskkill', 'killall', 'pkill', '--shutdown', '--terminate', 'maeve_console.py', 'maeve_farm_manager_bridge.py'):
                self.assertNotIn(prohibited, source)
        self.assertIn('process.wait(timeout=10)', inspect.getsource(broker.SttService.stop))

    def test_no_bytecode_children(self):
        self.assertEqual(LAUNCHER.controlled_environment()['PYTHONDONTWRITEBYTECODE'], '1')


if __name__ == '__main__':
    unittest.main()
