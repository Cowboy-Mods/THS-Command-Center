# Maeve V2 headset voice runtime

This directory contains the portable release candidate for Maeve's certified computer-based headset voice runtime. It provides two explicit operator modes:

- **Review Mode** records one physically held capture, performs local speech-to-text, and waits for transcript review before reasoning or speech.
- **Controlled Conversation** runs a continuous, bounded back-and-forth session after one explicit start. The microphone stays closed while Maeve processes and speaks, then reopens only after playback and a silent 650 ms pause.

Wake-word and open-room operation are not implemented or certified.

## Before starting

1. Install the required Windows Python runtime, official Codex client, and local WSL STT environment.
2. Copy `config.example.json` to `config.local.json`.
3. Fill in local executable, runtime, WSL, model, microphone, port and required `voice.voice_id` settings. The template's voice placeholder is deliberately invalid. Supply your own authorized voice resource locally; never paste its value into issues, logs, commands, environment files or source control. Never add an API key or token field.
4. Configure the ElevenLabs credential with `python .\scripts\configure-elevenlabs-credential.py set-gui`.
5. Confirm the configured runtime root identifies this directory and the approved microphone selector matches exactly one physical browser input.

The provider secret is stored and read only through Windows Credential Manager. Startup fails closed when configuration is absent, malformed, non-loopback, incomplete, or points to unavailable required executables.

## Starting Maeve

Configure the non-secret `MAEVE_PYTHON` Windows environment setting to the exact Python executable configured in your local JSON (Python 3.11 or newer). Then use `START MAEVE.cmd`. There is no PATH, Store-alias or unrelated virtual-environment fallback. The launcher checks its ports, checks stopped WSL state, creates a fresh memory-only authentication token, starts only its owned broker, and waits up to 120 seconds for authenticated broker and persistent-STT readiness before opening a dedicated Edge instance. Both Python commands retain `-B` and `PYTHONDONTWRITEBYTECODE=1`.

The voice resource setting stays in ignored local JSON and process memory; it is not exported to the environment or browser configuration. Syntax validation is not a claim that an account owns a resource. Credential access and any real provider use require deliberate operator setup and authorization. Missing or malformed voice configuration fails closed without a credential lookup or provider request.

Do not speak until the interface visibly says `LISTENING`.

## Review Mode

Select Review Mode, deliberately arm the control, hold push-to-talk only while speaking, and release it. Review or edit the local transcript, then approve once or discard it. A failed provider request is never retried automatically.

## Controlled Conversation

Press `START CONVERSATION` once and speak only while `LISTENING` is visible. Maeve closes the microphone during STT, reasoning, voice generation, and playback. After playback, Maeve waits 650 ms without a tone, displays `LISTENING`, and reopens the configured microphone. `MUTE` closes and blocks it; deliberate `UNMUTE` resumes it; `END CONVERSATION` closes it, invalidates delayed callbacks, releases owned audio, and stops the session.

Qwen remains an explicit manual local selection and is never an automatic fallback.

## Clean shutdown and failures

Open **CONTROL → CLOSE MAEVE**. Cancel leaves the runtime running. **END AND CLOSE** closes the microphone, clears the conversation, then requests authenticated graceful shutdown. Duplicate confirmation is ignored. The launcher waits for its dedicated browser and stops only recorded child handles; it never searches for generic Python or similarly named THS processes. A failed graceful shutdown uses only the existing exact-owned-child fallback. A sanitized failure does not trigger an automatic retry. Ctrl+C is a manual recovery path, not the normal interface.

Dedicated browser profiles are retained outside the repository pending independent ownership and inventory verification; they are not public-release artifacts. Do not remove or reuse unrelated browser profiles.

- If readiness fails, correct the named local prerequisite; do not loop.
- If STT fails, no transcript is accepted and no reasoning or voice request should occur.
- If ElevenLabs fails, there is no automatic retry, fallback, or sentence splitting.
- If microphone identity changes, reload only after correcting local configuration.
- Audio, transcript, session identity, and response data remain memory-only.

## Security boundary

- IPv4 loopback services only
- Fresh authenticated requests and strict origin/CSP checks
- Persistent network-isolated STT
- Windows Credential Manager as the sole provider-secret source
- No automatic paid-provider retry, fallback, or sentence splitting
- No microphone/playback overlap
- No committed local configuration, models, evidence, logs, audio, or credentials

## Integrated interface and certification boundary

Home, Clean View, nine fictional crew cards, focused views, mobile safe-area layouts and central Close Maeve controls are included. The separate owner card intentionally has no private real-person photograph. Specialist voice controls stay disabled; no hidden Maeve voice fallback exists. The bottom waveform is playback-only and remains still during listening and processing. The independent 3.6-second idle halo breathes when ready, respects reduced motion, and stops in ended/muted states; processing has a separate indicator.

The private installation's physical certification is not certification of a different operator's configuration. This portable release is validated offline with mocked services. Remote access, file transfer, Open Room, wake word and specialist routing remain unavailable. No printer, database, payment, message or other operational action is enabled by this package.

## Offline developer validation

Use a dedicated development Python installation and run `python -B qa/run_static.py` from this directory. The runner denies network and native credential access and uses temporary synthetic ledgers outside the release. It does not start Maeve.

Install the exact development dependencies in `package.json` in an isolated development environment, with browser downloads disabled, and make them resolvable to Node. Use an installed Microsoft Edge. Set `MAEVE_QA_ROOT` to this release directory and `MAEVE_QA_TEMP` to a new temporary directory outside the repository, then run `node qa/offline_edge.cjs TEST_NAME` for each of the six `test_*.cjs` UI suites. Do not run those suites directly: the wrapper owns the loopback-only server and blocks real endpoints, non-loopback requests, audio and device permissions. Screenshots and evidence stay in the temporary directory, never the package. The wrapper closes its browser and server on completion.

`config.local.json`, equivalent local configuration, caches, dependencies and evidence are excluded from the reviewed release allowlist. No operational voice or provider test is part of this validation.
