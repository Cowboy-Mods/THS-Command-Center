# Maeve V2 headset voice runtime

This directory contains the portable release candidate for Maeve's certified computer-based headset voice runtime. It provides two explicit operator modes:

- **Review Mode** records one physically held capture, performs local speech-to-text, and waits for transcript review before reasoning or speech.
- **Controlled Conversation** runs a continuous, bounded back-and-forth session after one explicit start. The microphone stays closed while Maeve processes and speaks, then reopens only after playback and a silent 650 ms pause.

Wake-word and open-room operation are not implemented or certified.

## Before starting

1. Install the required Windows Python runtime, official Codex client, and local WSL STT environment.
2. Copy `config.example.json` to `config.local.json`.
3. Fill in only local executable, runtime, WSL, model, microphone, and port values. Never add an API key or token field.
4. Configure the ElevenLabs credential with `python .\scripts\configure-elevenlabs-credential.py set-gui`.
5. Confirm the configured runtime root identifies this directory and the approved microphone selector matches exactly one physical browser input.

The provider secret is stored and read only through Windows Credential Manager. Startup fails closed when configuration is absent, malformed, non-loopback, incomplete, or points to unavailable required executables.

## Starting Maeve

Run `python .\scripts\start-windows.py --open-browser` from this directory. The launcher checks its ports, confirms Maeve WSL distributions are stopped, creates a fresh memory-only authentication token, starts only its owned broker, and waits up to 120 seconds for authenticated broker and persistent-STT readiness before opening the browser.

Do not speak until the interface visibly says `LISTENING`.

## Review Mode

Select Review Mode, deliberately arm the control, hold push-to-talk only while speaking, and release it. Review or edit the local transcript, then approve once or discard it. A failed provider request is never retried automatically.

## Controlled Conversation

Press `START CONVERSATION` once and speak only while `LISTENING` is visible. Maeve closes the microphone during STT, reasoning, voice generation, and playback. After playback, Maeve waits 650 ms without a tone, displays `LISTENING`, and reopens the configured microphone. `MUTE` closes and blocks it; deliberate `UNMUTE` resumes it; `END CONVERSATION` closes it, invalidates delayed callbacks, releases owned audio, and stops the session.

Qwen remains an explicit manual local selection and is never an automatic fallback.

## Clean shutdown and failures

Press `Ctrl+C` in the launcher terminal. The launcher stops only its child processes and verifies its ports are closed. Do not terminate unrelated THS Command Center processes.

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
