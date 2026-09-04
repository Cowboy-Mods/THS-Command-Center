import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "ui" / "styles" / "integrated-ui.css").read_text(encoding="utf-8")
VISUAL_CSS = (ROOT / "ui" / "styles" / "visual-correction.css").read_text(encoding="utf-8")
MANIFEST = (ROOT / "ui" / "manifest.webmanifest").read_text(encoding="utf-8")
MOBILE_PHASES = (ROOT / "MOBILE_CONNECTION_PHASES.md").read_text(encoding="utf-8")
UI = (ROOT / "ui" / "scripts" / "integrated-ui.js").read_text(encoding="utf-8")
HALO = (ROOT / "ui" / "scripts" / "halo-analyzer.js").read_text(encoding="utf-8")
RUNTIME = (ROOT / "ui" / "scripts" / "runtime.js").read_text(encoding="utf-8")
CONVERSATION = (ROOT / "ui" / "scripts" / "conversation-controller.js").read_text(encoding="utf-8")
SERVER = (ROOT / "broker" / "server.py").read_text(encoding="utf-8")


class IntegratedUiTests(unittest.TestCase):
    def test_all_seven_tabs_and_panels_exist(self):
        names = ("home", "crew", "comms", "schedule", "library", "docs", "control")
        for name in names:
            self.assertIn(f'data-view="{name}"', HTML)
            self.assertIn(f'data-view-panel="{name}"', HTML)
        self.assertIn("function openView(name)", UI)

    def test_authoritative_nine_person_roster(self):
        names = ("MAEVE", "ADDIE", "MADDIE", "CALLIE", "ISLA", "JUNIOR / BUB", "OLIVER", "AIDEN", "SHOP OPS")
        for name in names:
            self.assertIn(f'name:"{name}"', UI)
        self.assertEqual(UI.count('name:"'), 9)
        for obsolete in ('name:"OPERATOR"', 'name:"QUARTERMASTER"', 'name:"DOC"', 'name:"OPS"', 'name:"SCOUT"', 'name:"FORGE"'):
            self.assertNotIn(obsolete, UI)
        self.assertIn('id:"shop-ops"', UI)
        self.assertIn('responsibilities:"PRINTERS · FILAMENT · INVENTORY · MAINTENANCE INTERPRETATION"', UI)
        self.assertIn("OWNER / FINAL AUTHORITY", HTML)
        self.assertIn("OUTSIDE THE NINE-PERSON CREW COUNT", HTML)
        self.assertIn("SEPARATE · EXCLUDED FROM ACTIVE ROSTER", HTML)

    def test_startup_stage_order_and_guard(self):
        order = ["broker", "stt", "voice", "voice-ready", "maeve-ready"]
        positions = [UI.index(f'"{stage}"') for stage in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Startup stage order violation", UI)
        self.assertIn("Startup stage was not checked", UI)

    def test_failure_controls_and_text_only_are_explicit(self):
        for text in ("SHOW DETAILS", "TRY AGAIN", "CLOSE MAEVE", "START TEXT-ONLY"):
            self.assertIn(text, HTML)
        self.assertIn('voiceOnly=false', UI)
        self.assertIn('textOnly.hidden=!voiceOnly', UI)
        self.assertIn('detail:{explicit:true}', UI)
        self.assertIn('maeve:retry-stage', UI)
        self.assertIn('maeve:close-requested', RUNTIME)
        close_control = (ROOT / 'ui/scripts/close-control.js').read_text(encoding='utf-8')
        self.assertIn('/api/runtime/close', close_control)
        self.assertIn('authorized:launchAuthorized', RUNTIME)
        self.assertIn('MAEVE_CLOSE_CONTROL.create', RUNTIME)
        self.assertIn('if(attempted||!config.authorized)return', close_control)
        self.assertIn('/api/runtime/close', SERVER)

    def test_no_fake_percentages_or_operational_values(self):
        self.assertIsNone(re.search(r"\b\d{1,3}%\b", HTML))
        for truth in ("NOT CONNECTED", "NO VERIFIED DATA", "SOURCE NOT CONFIGURED", "MONITORING COMING IN LATER STAGE"):
            self.assertIn(truth, HTML)

    def test_open_room_is_disabled_and_truthful(self):
        self.assertIn("NOT YET AVAILABLE", HTML)
        self.assertIn("OPEN ROOM ARMED", HTML)
        self.assertRegex(HTML, r'<input type="checkbox" disabled> OPEN ROOM ARMED')
        self.assertNotIn("getUserMedia", UI)

    def test_large_voice_safety_controls(self):
        self.assertIn('class="mute-control"', HTML)
        self.assertIn('class="end-control"', HTML)
        self.assertIn("min-height:64px", CSS)

    def test_certified_conversation_states_and_end_interlock_remain(self):
        for state in ("LISTENING", "THINKING", "SPEAKING", "MUTED", "OFF", "FAILED"):
            self.assertIn(state, CONVERSATION + RUNTIME + HTML)
        self.assertIn('cleanup("end"', CONVERSATION)
        self.assertIn('finalizeLocal("OFF"', CONVERSATION)
        self.assertIn("MICROPHONE CLOSED", CONVERSATION)

    def test_existing_halo_contract_and_assets_remain(self):
        self.assertIn("maeve_foreground_transparent_v2.png", HTML)
        self.assertIn("maeve-halo", HTML)
        self.assertIn("MAEVE_HALO_ANALYZER", RUNTIME)
        self.assertIn("REAL AUDIO ANALYZER ACTIVE", RUNTIME)

    def test_responsive_desktop_breakpoints(self):
        self.assertIn("@media(max-width:1700px)", CSS)
        self.assertIn("@media(max-width:1250px)", CSS)
        self.assertIn("@media(max-height:900px)", CSS)
        self.assertRegex(CSS, r"\.view\{[^}]*overflow-y:auto")
        self.assertRegex(CSS, r"\.structured-view\{[^}]*overflow-y:auto")
        self.assertRegex(CSS, r"\.structured-view\{[^}]*padding-bottom:88px")

    def test_portraits_are_local_and_unresolved_people_are_explicit(self):
        for asset in ("maeve_crew_portrait_photoreal_v2.png", "addie_quartermaster_portrait_photoreal_v2.png", "maddie_doc_portrait_photoreal_v2.png", "isla_scout_portrait_photoreal_v2.png", "oliver_forge_portrait_photoreal_v2.png"):
            self.assertIn(asset, UI)
            self.assertTrue((ROOT / "ui" / "assets" / "crew" / asset).is_file())
        self.assertIn('src="./assets/maeve_foreground_transparent_v2.png"', HTML)
        self.assertIn('class="maeve-focus-portrait" src="./assets/crew/maeve_crew_portrait_photoreal_v2.png"', HTML)
        self.assertIn("Operator portrait not configured", HTML)
        for asset in ("callie_relay_portrait_v1.png", "junior_bub_hammer_portrait_v1.png", "aiden_broker_portrait_v1.png", "shop_ops_female_portrait_v1.png"):
            self.assertIn(asset, UI)
        self.assertEqual(UI.count("portrait:null"), 0)
        self.assertNotIn("ops_portrait_rgba_v1.png", UI + HTML)
        self.assertNotIn("shop_ops_portrait_rgba_v1.png", UI + HTML)

    def test_focused_conversation_mode_is_deliberate_and_truthful(self):
        self.assertIn('id="maeve-command-stage" role="button" tabindex="0"', HTML)
        self.assertIn("function openConversationMode()", UI)
        self.assertIn('query.get("focus")==="conversation"', UI)
        self.assertIn("RETURN TO COMMAND CENTER", HTML)
        self.assertNotIn("getUserMedia", UI)
        self.assertNotIn("onMicAmplitude", CONVERSATION)
        self.assertIn("MAEVE_HALO_ANALYZER.applyValues", RUNTIME)
        self.assertIn("halo-waveform", HTML)
        self.assertNotIn('class="halo-modulator"', HTML)

    def test_wavy_halo_uses_real_audio_paths_and_processing_is_separate(self):
        self.assertIn('id="halo-waveform"', HTML)
        self.assertIn('id="halo-processing"', HTML)
        self.assertIn("radialWavePath", HALO)
        self.assertIn("analyser.getByteFrequencyData", HALO)
        self.assertNotIn("onMicAmplitude", CONVERSATION)
        self.assertIn("createMediaStreamSource", CONVERSATION)
        self.assertIn("createBufferSource", RUNTIME)
        self.assertIn("MAEVE_HALO_ANALYZER.create", RUNTIME)
        self.assertIn('body[data-voice-state="PROCESSING_STT"] .halo-processing', VISUAL_CSS)
        self.assertIn("prefers-reduced-motion:reduce", VISUAL_CSS)

    def test_clean_view_controls_and_glass_panels(self):
        for control in ("CLEAN VIEW", "RESTORE COMMAND VIEW", ">STATUS<", ">VOICE<"):
            self.assertIn(control, HTML)
        self.assertIn("function setCleanView(enabled)", UI)
        self.assertIn("clean-view .mission-column", VISUAL_CSS)
        self.assertIn("clean-view .voice-command-column", VISUAL_CSS)
        self.assertIn("backdrop-filter:blur", VISUAL_CSS)

    def test_mobile_pwa_foundation_is_local_and_truthful(self):
        self.assertIn("viewport-fit=cover", HTML)
        self.assertIn('rel="manifest"', HTML)
        self.assertIn('rel="apple-touch-icon"', HTML)
        for value in ('"name": "Maeve — THS Command Center"', '"short_name": "Maeve"', '"display": "standalone"', '"background_color": "#050708"', '"theme_color": "#050708"'):
            self.assertIn(value, MANIFEST)
        self.assertNotIn("http://", MANIFEST)
        self.assertNotIn("https://", MANIFEST)
        self.assertIn("selectMobilePanel", UI)
        self.assertIn("mobile-voice-selected", UI + VISUAL_CSS)
        self.assertIn("env(safe-area-inset-bottom)", VISUAL_CSS)
        self.assertIn("Never directly expose Maeve's broker port", MOBILE_PHASES)
        self.assertIn("127.0.0.1", MOBILE_PHASES)

    def test_crew_cards_are_keyboard_native_and_routing_disabled(self):
        self.assertIn('<button class="roster-row" type="button"', UI)
        self.assertIn("openCrewDetail", UI)
        self.assertIn("RETURN TO FULL ROSTER", HTML)
        self.assertIn("ROUTING NOT YET CONNECTED", HTML)
        self.assertRegex(CSS, r"\.roster-row:hover,\.roster-row:focus-visible")


if __name__ == "__main__":
    unittest.main()
