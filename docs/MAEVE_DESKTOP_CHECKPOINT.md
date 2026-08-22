# Maeve Desktop Checkpoint (Historical)

> Superseded by `MAEVE_LIVE_CHECKPOINT_2026-08-22.md`. This file preserves the
> pre-installation baseline and must not be used as the current operating state.

Date: 2026-08-21

- Branch preserved: `feature/p1s-read-only-telemetry`.
- Pre-existing dashboard script changes and backups were preserved.
- Docker Desktop 4.87.0 and official OctoEverywhere Docker references are staged
  under `C:\THS\Installers\OctoEverywhere`; nothing was executed.
- BIOS SVM is disabled, WSL is absent, and a pending-reboot flag remains.
- Sanitized schema, offline/fixture providers, atomic state/feed writer, and
  localhost GET-only gateway are implemented with no live provider.
- Rainmeter and dashboard consume sanitized state only; final state is OFFLINE.
- Full regression validation passed on 2026-08-21: 390 tests in 715.668 seconds.
- Rainmeter fixture validation covered 14 offline/demo states; the final loaded
  panel was restored to `OFFLINE / CONNECTION NOT CONFIGURED` at X=0, Y=1064.
- The Clock, System, Launcher, and Weather skin hashes remained at their
  pre-work baselines, and no localhost Maeve gateway was left listening.
- No account, credential, printer connection, command, inventory write, firewall
  rule, container, WSL feature, or restart occurred.

Next physical action: during a safe maintenance window, enable ASUS SVM in UEFI,
restart, and run `scripts\maeve-preflight.ps1` from an elevated PowerShell.
Do not proceed past any failed preflight, restart, terms, account, or credential
gate.
