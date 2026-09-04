"""Portable privacy, asset and fail-closed configuration regression coverage."""
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from runtime_config import ConfigurationError, export_environment, load_config
from test_portable_config import fixture


def private_matches(root, forbidden):
    """Return relative paths only; never echo the comparison value or file text."""
    if not isinstance(forbidden, bytes) or not forbidden:
        raise ValueError('Private comparison value required')
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*')
                  if p.is_file() and forbidden in p.read_bytes())


class PublicReleaseTests(unittest.TestCase):
    def test_scanner_classifies_without_disclosing_value(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            sentinel = b'synthetic-private-comparison-only'
            (root / 'fixture.txt').write_bytes(sentinel)
            self.assertEqual(private_matches(root, sentinel), ['fixture.txt'])
            self.assertNotIn(sentinel.decode(), repr(private_matches(root, sentinel)))

    def test_template_voice_is_deliberately_nonfunctional(self):
        raw = json.loads((ROOT / 'config.example.json').read_text())
        self.assertEqual(raw['voice']['voice_id'], 'REQUIRED_LOCAL_VOICE_ID_NOT_CONFIGURED')
        with self.assertRaises(ConfigurationError):
            load_config(ROOT / 'config.example.json', require_local_files=False)

    def test_missing_local_configuration_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigurationError):
                load_config(Path(d) / 'missing.json', require_local_files=False)

    def test_voice_not_exported_to_environment(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'fixture.json'
            p.write_text(json.dumps(fixture()))
            config = load_config(p, require_local_files=False)
            exported = export_environment(config)
            self.assertNotIn('voice_id', exported)
            self.assertNotIn(config['voice_id'], json.dumps(exported))

    def test_public_assets_match_public_provenance(self):
        provenance = (ROOT / 'ASSET_PROVENANCE.md').read_text(encoding='utf-8')
        rows = re.findall(r'`(ui/assets/[^`]+)` \| \d+×\d+ \| `([A-F0-9]{64})`', provenance)
        self.assertEqual(len(rows), 11)
        for relative, digest in rows:
            self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest().upper(), digest)

    def test_voice_configuration_is_not_in_browser_endpoint(self):
        source = (ROOT / 'broker/server.py').read_text(encoding='utf-8')
        route = source.split('if path == "/api/config":', 1)[1].split('if path ==', 1)[0]
        self.assertNotIn('voice_id', route)
        self.assertIn('"microphone"', route)

    def test_local_state_excluded(self):
        ignored = (ROOT / '.gitignore').read_text()
        for item in ('config.local.json', '.env', '__pycache__/', '*.pyc', 'node_modules/', 'evidence/'):
            self.assertIn(item, ignored)
        self.assertFalse((ROOT / 'config.local.json').exists())

    def test_ui_dependencies_are_local_and_present(self):
        html = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        for reference in re.findall(r'(?:src|href)="(\./[^"#]+)"', html):
            self.assertTrue((ROOT / 'ui' / urlsplit(reference).path).is_file(), reference)
        for css in (ROOT / 'ui/styles').glob('*.css'):
            for reference in re.findall(r'url\(["\']?([^\)"\']+)', css.read_text(encoding='utf-8')):
                if reference.startswith('#') or reference.startswith('data:'):
                    continue
                self.assertNotIn('://', reference)
                self.assertTrue((css.parent / reference).is_file(), reference)

    def test_microphone_cannot_drive_voice_waveform(self):
        controller = (ROOT / 'ui/scripts/conversation-controller.js').read_text(encoding='utf-8')
        self.assertNotIn('onMicAmplitude', controller)
        self.assertNotIn('MAEVE_VOICE_DISPLAY', controller)
        runtime = (ROOT / 'ui/scripts/runtime.js').read_text(encoding='utf-8')
        self.assertIn('createBufferSource()', runtime)
        self.assertIn('MAEVE_HALO_ANALYZER.create(audioContext,source', runtime)
