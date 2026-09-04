# Portable integrated Maeve release

This release contains the integrated Home/Clean View, nine fictional crew portraits and focus screens, responsive layouts, separate idle halo and playback-only waveform, authenticated Close Maeve, and recorded-child launcher cleanup. Private installation settings and the real-person owner portrait are excluded.

## Offline validation

- 67 unit tests passed; broker QA and 218 Controlled Conversation assertions passed.
- Portable configuration and mocked provider tests passed, including missing/invalid voice configuration, no environment/browser voice-ID export, no silent fallback and no credential lookup before valid configuration.
- Python syntax and 17 JavaScript/CommonJS syntax checks passed.
- Six headless Edge suites passed: Close Maeve, desktop layout, specialist focus, halo layering, idle halo and playback-only waveform.
- Specialist mappings: 54 focused viewport checks and 24 preserved-layout comparisons. Halo: 50 focused visibility checks. Playback-only: 27 state checks.
- All 11 image hashes match the public provenance record; nine new fictional crew files were copied unchanged.
- The private resource comparison found zero resulting-file or added/context-line matches. One deletion line removes the pre-existing literal; existing history is preserved. The comparison value is never recorded here.
- Device, provider, STT, reasoning, playback, printer, database and operational service calls: zero. Headless fixtures are not a physical operator certification.

A first Close Maeve preview assertion found an uninitialized-controller READY label; explicit no-controller cleanup now sets OFF and the suite passed. A dependency test was corrected to resolve URL query strings separately from file paths. No private production files were changed.

## Remaining boundaries

Local setup is required. The template voice value cannot work. Credentials belong only in Windows Credential Manager; the resource setting belongs only in ignored operator-local JSON. No specialist voice, Open Room, wake word, remote access, file transfer or operational integration is enabled. No automatic retry or fallback is added. Dedicated browser profiles remain outside the package for controlled cleanup.

## Exact reviewed changed-path allowlist

- `maeve/voice-runtime/.gitignore`
- `maeve/voice-runtime/ASSET_PROVENANCE.md`
- `maeve/voice-runtime/MOBILE_CONNECTION_PHASES.md`
- `maeve/voice-runtime/README.md`
- `maeve/voice-runtime/RELEASE_NOTES.md`
- `maeve/voice-runtime/START MAEVE.cmd`
- `maeve/voice-runtime/broker/conversation_policy.py`
- `maeve/voice-runtime/broker/server.py`
- `maeve/voice-runtime/broker/voice_provider.py`
- `maeve/voice-runtime/config.example.json`
- `maeve/voice-runtime/package.json`
- `maeve/voice-runtime/qa/offline_edge.cjs`
- `maeve/voice-runtime/qa/rehearsal_guard.py`
- `maeve/voice-runtime/qa/run_static.py`
- `maeve/voice-runtime/qa/scan_private_value.py`
- `maeve/voice-runtime/qa/subprocess_guard.py`
- `maeve/voice-runtime/qa/test_broker.py`
- `maeve/voice-runtime/qa/test_close_control.cjs`
- `maeve/voice-runtime/qa/test_close_control.py`
- `maeve/voice-runtime/qa/test_desktop_correction.cjs`
- `maeve/voice-runtime/qa/test_halo_layer.cjs`
- `maeve/voice-runtime/qa/test_idle_halo.cjs`
- `maeve/voice-runtime/qa/test_integrated_ui.py`
- `maeve/voice-runtime/qa/test_launch_ownership.py`
- `maeve/voice-runtime/qa/test_launcher.py`
- `maeve/voice-runtime/qa/test_playback_only.cjs`
- `maeve/voice-runtime/qa/test_portable_config.py`
- `maeve/voice-runtime/qa/test_public_release.py`
- `maeve/voice-runtime/qa/test_specialist_focus.cjs`
- `maeve/voice-runtime/qa/test_specialist_focus.py`
- `maeve/voice-runtime/qa/test_subprocess_guard.py`
- `maeve/voice-runtime/qa/test_validation_isolation.py`
- `maeve/voice-runtime/qa/test_voice_provider.py`
- `maeve/voice-runtime/qa/validation_isolation.py`
- `maeve/voice-runtime/runtime_config.py`
- `maeve/voice-runtime/scripts/start-windows.py`
- `maeve/voice-runtime/ui/assets/crew/addie_quartermaster_portrait_photoreal_v2.png`
- `maeve/voice-runtime/ui/assets/crew/aiden_broker_portrait_v1.png`
- `maeve/voice-runtime/ui/assets/crew/callie_relay_portrait_v1.png`
- `maeve/voice-runtime/ui/assets/crew/isla_scout_portrait_photoreal_v2.png`
- `maeve/voice-runtime/ui/assets/crew/junior_bub_hammer_portrait_v1.png`
- `maeve/voice-runtime/ui/assets/crew/maddie_doc_portrait_photoreal_v2.png`
- `maeve/voice-runtime/ui/assets/crew/maeve_crew_portrait_photoreal_v2.png`
- `maeve/voice-runtime/ui/assets/crew/oliver_forge_portrait_photoreal_v2.png`
- `maeve/voice-runtime/ui/assets/crew/shop_ops_female_portrait_v1.png`
- `maeve/voice-runtime/ui/index.html`
- `maeve/voice-runtime/ui/manifest.webmanifest`
- `maeve/voice-runtime/ui/scripts/close-control.js`
- `maeve/voice-runtime/ui/scripts/conversation-controller.js`
- `maeve/voice-runtime/ui/scripts/halo-analyzer.js`
- `maeve/voice-runtime/ui/scripts/idle-halo.js`
- `maeve/voice-runtime/ui/scripts/integrated-ui.js`
- `maeve/voice-runtime/ui/scripts/runtime.js`
- `maeve/voice-runtime/ui/scripts/specialist-focus.js`
- `maeve/voice-runtime/ui/scripts/voice-display.js`
- `maeve/voice-runtime/ui/styles/close-control.css`
- `maeve/voice-runtime/ui/styles/desktop-readability.css`
- `maeve/voice-runtime/ui/styles/focused-halo-layer.css`
- `maeve/voice-runtime/ui/styles/idle-halo.css`
- `maeve/voice-runtime/ui/styles/integrated-ui.css`
- `maeve/voice-runtime/ui/styles/specialist-focus.css`
- `maeve/voice-runtime/ui/styles/visual-correction.css`
- `maeve/voice-runtime/worker/qwen_worker.py`
