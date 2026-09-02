# Maeve Desktop Telemetry Foundation

Date: 2026-08-21
Host: the operator's Windows 11 desktop, temporarily

## Current boundary

Maeve's Raspberry Pi, display, camera, microphone, speakers, and final enclosure
hardware have not been purchased. The owned USB hub and switches are retained
for the future build. The Windows desktop is the temporary software host.

The P1S remains cloud-bound with LAN Mode OFF and Developer Mode OFF. Its
observed private address is intentionally omitted, the Eero reservation is not complete, and
the address is not an authoritative configuration value. No printer connection
is made by this foundation.

## Architecture

`inventory.maeve_telemetry` defines schema `1.0`, provider interfaces, strict
validation, offline and fixture providers, freshness rules, atomic JSON state,
an atomic Rainmeter feed, and an inventory-comparison projection. The THS-facing
contract always reports `control_capable=false` and contains no credentials,
serial, account token, email, printer address, command, G-code, file operation,
or action queue.

`scripts/maeve_telemetry_gateway.py` is a standard-library Windows gateway. It
binds only to `127.0.0.1` and exposes only:

- `GET /health`
- `GET /status`
- `GET /rainmeter`

POST, PUT, PATCH, and DELETE return 405. Non-loopback binding is rejected.
There is no WebSocket, MQTT publisher, printer adapter, or control route. The
gateway is not installed as a service tonight and is left stopped.

## Field and fallback contract

The contract includes provider, printer model/display name, connection and
printer states, job/plate, progress, remaining seconds/formatted time, layers,
nozzle/bed actual and target temperatures, optional chamber temperature, active
AMS/slot, filament type/color, both AMS humidity values, warning code/text,
source/gateway update times, age, stale/offline flags, source health, safe
provenance, and the permanently false control-capability flag.

Unknown scalar values are `null` in JSON and readable `N/A` or `NOT REPORTED`
in display feeds. Missing, invalid, expired, or unavailable sources fail closed
to OFFLINE. Fixture data is possible only through an explicit fixture name and
is visibly labeled `DEMO / ... / TEST DATA`.

## Docker and OctoEverywhere gate

The official Docker Desktop 4.87.0 installer is staged but not executed because
BIOS SVM is disabled, WSL is absent, and Windows has a pending-reboot indicator.
The official OctoEverywhere documentation is staged for later review. Account
linking and printer credentials remain personal interactive gates.

## Post-BIOS procedure

This computer has a `<HOST_MOTHERBOARD_MODEL>` motherboard. On the verified host:

1. Restart only when no print or other critical work can be disrupted.
2. Press the motherboard vendor's setup key repeatedly during startup to enter UEFI.
3. Press `F7` for Advanced Mode.
4. Open **Advanced > CPU Configuration > SVM Mode**.
5. Set **SVM Mode** to **Enabled**.
6. Press `F10`, review that SVM is the intended change, and save/restart.

UEFI menu wording can vary by motherboard and firmware. If `SVM Mode` is not in
that exact location, stop and identify the motherboard model before changing a
different option.

After Windows returns, open an elevated PowerShell and run the preflight:

`& '<REPOSITORY_ROOT>/scripts/maeve-preflight.ps1'`

If WSL is still absent, the operator must explicitly authorize the administrator-run
WSL installation and its required restart. After every gate passes, verify the
installer without running it:

`& '<REPOSITORY_ROOT>/scripts/resume-maeve-install.ps1'`

Only while the operator is present, add `-InstallDocker` to open the interactive
official installer. Stop at Docker terms, restart, OctoEverywhere account, and
private access-code entry gates. Do not enable Kubernetes or firewall ports.

## Future Pi migration

Move only the provider and gateway runtime to the future Pi. Keep schema `1.0`,
the sanitized state contract, Rainmeter/dashboard consumers, and fail-closed
behavior. Re-create secrets through an approved protected store; never copy a
Windows DPAPI blob to the Pi.
