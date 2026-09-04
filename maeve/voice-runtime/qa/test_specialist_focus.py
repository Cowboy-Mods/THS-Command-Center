import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'ui/scripts/specialist-focus.js').read_text(encoding='utf-8')
CSS = (ROOT / 'ui/styles/specialist-focus.css').read_text(encoding='utf-8')

class SpecialistFocusTests(unittest.TestCase):
    def test_no_network_or_voice_fallback(self):
        for forbidden in ('fetch(', 'apiFetch', 'getUserMedia', 'AudioContext', '.play(', 'conversation-start', 'dispatchEvent'):
            self.assertNotIn(forbidden, JS)

    def test_native_modal_and_disabled_controls(self):
        self.assertIn('screen.showModal()', JS)
        self.assertEqual(JS.count('type="button" disabled'), 4)
        self.assertIn('SPECIALIST VOICE — NOT YET CONNECTED', JS)
        self.assertIn('screen.addEventListener("cancel"', JS)

    def test_shared_authoritative_mapping_and_no_invented_crew(self):
        self.assertIn('ui.crew.find', JS)
        self.assertIn('portrait.src = member.portrait', JS)
        self.assertIn('TALK TO ${member.name}', JS)
        self.assertIn('ui.openView("home")', JS)
        self.assertIn('ui.openView("crew")', JS)

    def test_mobile_scoped_and_inactive_wave(self):
        self.assertIn('env(safe-area-inset-bottom)', CSS)
        self.assertIn('@media(max-width:700px)', CSS)
        self.assertIn('"M 28 70 L 372 70"', JS)
        self.assertNotIn('MAEVE_HALO_ANALYZER', JS)

if __name__ == '__main__':
    unittest.main()
