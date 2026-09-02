# Maeve V2 certified headset voice milestone

This milestone introduces Maeve's computer-based headset voice release candidate into THS Command Center history.

## Certified behavior

- Physical Review Mode
- Continuous Controlled Conversation under one explicit start
- Persistent local faster-whisper speech-to-text
- Maeve - Dublin Command through `eleven_flash_v2_5` at speed 0.90
- Memory-only capture, response audio, and playback
- Real-audio halo behavior
- Microphone closed throughout processing and playback
- Visible `LISTENING` state before capture
- Silent 650 ms post-playback relisten boundary
- MUTE, deliberate UNMUTE, and END safeguards
- Qwen starts zero while ElevenLabs is selected

ElevenLabs credentials are obtained exclusively through Windows Credential Manager. The runtime performs no automatic paid-provider retry, sentence splitting, or fallback.

## Scope boundary

Wake-word and open-room operation are not implemented or certified. This public milestone contains no credential, transcript, audio, private certification evidence, provider ledger, model weight, WSL image, or machine-specific local configuration.

The detailed laboratory certification and rollback records remain private and outside this repository.
