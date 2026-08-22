# Bambu Studio Passive Telemetry Decision

Date: 2026-08-20
Decision: implementation gate failed; keep THS Print Watch offline-safe

## Safety boundary

This investigation inspected existing local files, metadata, process-owned
connections, IPC state, event summaries, and THS foundations. It did not open a
new connection to the printer, probe a printer port, authenticate, subscribe,
publish, decrypt traffic, extract credentials, or interact with Bambu Studio.

## Candidate assessment

| Candidate | Passive evidence | Requested fields | Security and stability judgment |
| --- | --- | --- | --- |
| Active encrypted Studio log under `%APPDATA%\BambuStudio\log` | Produced by the running Bambu Studio process and grew by about 61 KB during a 20-second sample | No readable job, progress, time, layer, temperature, AMS, or warning fields | Fails. The content is encrypted/private diagnostic data, its format is undocumented, and a permanent parser would be update-fragile. |
| Encrypted network debug log under `%APPDATA%\BambuStudio\log` | Produced by Bambu Studio but unchanged during the sample | No readable requested fields | Fails. Encrypted diagnostic output is not a supported telemetry interface. |
| `BambuStudio.conf` | Static during the sample | No requested live telemetry keys | Fails. It contains account/session-related configuration and is not a live status feed. |
| `BambuNetworkEngine.conf` | Static binary configuration | No readable requested fields | Fails. It is private engine configuration and not a stable status contract. |
| `log_iotc.txt` | Static during the sample | No requested live telemetry fields | Fails. It is authentication/diagnostic-oriented and not a current status feed. |
| `filament_inventory`, `track`, `cache`, and `ota` | No requested telemetry-key hits; files were static or unrelated catalog/history data | None sufficient for Print Watch | Fails. These are not active printer-state projections. |
| Bambu Studio loopback TCP pair | Internal self-connection owned by Bambu Studio; no process-owned listener was exposed | Unknown and not inspected | Fails. Consuming or reverse-engineering private IPC would be unstable and could interfere with Studio. |
| Bambu-named pipes | None found | None | Fails. No candidate endpoint exists. |
| Windows Application event log | No relevant Bambu status events found | None | Fails. No telemetry source exists there. |
| THS runtime/database | No watcher process, no runtime telemetry files, and zero equipment telemetry rows | Offline foundations only | Fails. Existing code and fixtures are not live observations. |

## Existing connection observation

The running Bambu Studio process already owned its normal established cloud
connection and an established TLS connection to the currently observed local
printer address. The investigation only enumerated those existing sockets; it
did not connect to either endpoint or read their traffic.

## Decision

No candidate meets the permanent integration gate. The only continuously
updated artifact is encrypted and undocumented, while readable files either
contain account-sensitive configuration or lack useful live telemetry. No
helper, cache, background process, or Rainmeter integration was created.

The existing `Bambu.ini` remains the approved offline-safe display.

## Current unlocked observation

- Observed P1S IP: private local value omitted from Git
- LAN Mode observed: `OFF`
- DHCP reservation: `NOT YET COMPLETED`
- Status: `CURRENT OBSERVATION, NOT LOCKED`

The temporary address is not an authoritative configuration value and telemetry
must not be activated against it.

## Safest next step

Keep the printer cloud-bound and the Rainmeter panel offline-safe. Review an
official, documented Bambu cloud-compatible read-only integration if Bambu
publishes one. Do not enable LAN Mode until the effects on Bambu Handy, cloud
printing, camera access, and Cowboy's normal Studio workflow are explicitly
reviewed.
