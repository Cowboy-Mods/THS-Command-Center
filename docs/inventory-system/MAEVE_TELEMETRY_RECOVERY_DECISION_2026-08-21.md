# Maeve P1S Telemetry Recovery Decision

Date: 2026-08-21
Status: research complete; no implementation authorized
Printer state during investigation: actively printing

## No-action-during-print statement

This investigation was passive and read-only. It did not open a printer connection,
authenticate, subscribe, publish, probe a printer port, operate Bambu Studio, alter
Maeve, change Rainmeter, download firmware, or issue a printer command. No recovery
option in this document may be activated until the printer is idle and Cowboy opens a
separate approval checkpoint.

## Executive decision

Keep Maeve camera-only and MQTT parked for the current print. The best candidate for
genuine structured telemetry is Bambu's official farm-management stack, because Bambu
now documents an authenticated local HTTP status API containing the requested job,
progress, remaining-time, layer, temperature, warning, camera-snapshot, and AMS fields.

That is a candidate, not an approved installation. The published API document is for
the physical Bambu Fleet Hub and references Bambu Farm Manager, but it does not prove
that the free Windows Farm Manager exposes the same supported client API. It also says
a printer in LAN-only mode cannot be bound to the Hub and that binding changes the
printer to farm mode. Those workflow effects must be verified before any installation
or printer change.

Until those questions are answered, the safe operational choice is **camera-only**.
Do not scrape Studio, reverse-engineer its encrypted files, use private cloud tokens,
or downgrade firmware merely to retry raw MQTT.

## Phase 1: passive Bambu Studio LAN audit

### Current local evidence

| Item | Read-only finding | Decision |
| --- | --- | --- |
| Bambu Studio | Running from its installed program directory; file version `02.08.02.60`; Authenticode signature valid | Existing supported Cowboy workflow; untouched |
| Network plug-in | `bambu_networking.dll` exists under Studio's roaming plug-in directory; Authenticode signature valid; no embedded file/product version resource | Signed official component, but build cannot be identified reliably from Windows version metadata |
| Process tree | One Studio process; normal command line only | No helper suitable for Maeve |
| Existing sockets | Studio already owned its normal cloud and local-printer TLS connections plus ephemeral network-plug-in endpoints | Enumerated only; no socket was duplicated, read, or contacted |
| Named pipes | No Bambu/Studio-named pipe found | No IPC candidate |
| Local web/status endpoint | No documented status endpoint found; ephemeral listeners were not probed | Not a supported integration surface |
| Structured files | Static printer definitions and filament inventory exist, but they are catalogs rather than live job state | Not telemetry |
| Configuration | Studio and network-engine configuration exists and may contain private session/account state | Excluded from consumption |
| Logs | The continuously active diagnostic artifacts are encrypted or undocumented | Not safe or stable to parse |
| SQLite/JSON live projection | No supported local database or JSON file carrying the requested advancing print state was found | No viable Studio-file source |

### Studio-source conclusion

No stable, documented, sanitized local Bambu Studio source passed the integration gate.
The live state appears to remain inside the signed proprietary network plug-in and the
Studio process. Consuming it would require an explicitly prohibited technique such as
private IPC reverse engineering, traffic interception, memory inspection, credential
access, or screen scraping. No offline fixture was copied because no qualifying source
was found.

## Phase 2: official Bambu software findings

### Officially documented facts

- Authorization Control protects binding, remote video initiation, firmware updates,
  print initiation, motion, temperatures, fans, AMS settings, and calibrations.
- Bambu says printer status pushes are not intended to require control authorization,
  and separately says monitoring such as temperature and status remains available to
  third-party software. Cowboy's current firmware behavior nevertheless closes Maeve's
  subscription after authentication, so the promise and observed P1S behavior do not
  presently align.
- Developer Mode deliberately leaves MQTT, live stream, and FTP open, but Bambu says
  those protocols are not officially supported.
- Bambu Connect is an official handoff/control application for file transmission and
  restricted operations. No public, documented, read-only telemetry API for Maeve was
  found.
- Bambu Farm Manager is a free Windows 10+ local-network product supporting P1, A1, and
  X1C printers. Bambu advertises real-time monitoring, queueing, local file handling,
  and no cloud requirement for its current core functionality.
- Bambu's Fleet Hub HTTP API v1.0.0 documents genuine status fields including job name,
  progress, remaining seconds, current/total layers, nozzle and bed temperatures,
  state, errors/HMS, camera snapshots, AMS presence, slots, filament type, and color.
  Its AMS representation supports multiple AMS/Pro units.
- The Fleet Hub API requires mTLS, device activation, and a local authenticated session.
  It describes the Hub as physical Print Control Box hardware. It does not establish
  that the downloadable Farm Manager server exposes this API to ordinary local clients.
- The Hub documentation says LAN-only printers are not bindable; binding changes a
  supported printer to `farm` mode and occupies the binding. This is not a transparent
  add-on to Cowboy's present LAN-only arrangement.

### Open-source implementation evidence

- Bambu Studio's open-source UI calls a separately delivered proprietary network
  plug-in. Public source does not provide a stable telemetry server contract for an
  external Maeve client.
- Established community integrations use reverse-engineered MQTT report messages.
  That establishes field precedent, not official support or compatibility with this
  P1S firmware.

### Community evidence

- Community reports place Authorization Control for P1 production firmware at
  `01.08.02.00` and describe older `01.08.00.00`/`01.08.01.00` as retaining the earlier
  raw-MQTT behavior.
- Reports also describe connectivity and status regressions in several Studio/network
  plug-in releases. These reports are useful warnings but are not proof of Cowboy's
  exact failure cause or of downgrade success.

### Inference

The documented Fleet status schema is the closest legitimate match for Maeve, but a
Farm Manager pilot is justified only if Bambu confirms the Windows server has a
supported read-only API and clarifies binding/coexistence. Otherwise the practical safe
choice remains camera-only until Bambu fixes or documents P1 status access.

## Phase 3: firmware compatibility comparison

`Unknown` means no reliable official statement was found. Direct MQTT entries below
combine official Authorization Control dates with clearly identified community
evidence; they are not an official MQTT compatibility guarantee.

| Firmware | Developer Mode / direct services | Studio, Handy, and cloud | AMS 2 Pro / two-unit considerations | Bugs, security, and downgrade |
| --- | --- | --- | --- | --- |
| `01.10.00.00` current | Developer Mode available. In Cowboy's verified tests, TLS and MQTT authentication succeeded but the exact report subscription was closed before SUBACK. Camera works. FTP was not tested here. | Current official workflow works. | Official notes add automatic drying presets, external-spool multicolor, PA protection, and a third-party-filament drying fix. Recommended companion AMS 2 Pro firmware is listed by Bambu. | Includes security updates. Official download is available. No downgrade was attempted. |
| `01.09.01.00` | Post-Authorization-Control; Developer Mode expected. Raw report compatibility with Maeve is unproven. | Intended for current Bambu software; current cloud compatibility not separately guaranteed here. | Adds a drying spool-rotation toggle and fixes AMS communication, multi-dryer, motor, and material-setting issues according to release-history evidence. | Officially downloadable and designated bridge firmware for later offline upgrades. Community connectivity complaints exist. |
| `01.09.00.00` | Post-Authorization-Control; Developer Mode expected. Raw report compatibility unproven. | Official notes do not identify a normal Studio/Handy break. | Official notes improve AMS RFID reliability and Farm Management network stability. Two-unit feeding is expected from the AMS architecture, but no official two-unit regression matrix was found. | Officially downloadable. Known official issues included a Handy stop-button problem during AMS loading and temporary E3D software gaps. |
| `01.08.02.00` | Official release-history evidence introduces Authorization Control and Developer Mode. Community evidence says direct MQTT becomes authorization-sensitive here. | Bambu Connect and offline/LAN workflows are advertised. | Retains AMS 2 Pro support introduced in 01.08.00; later AMS fixes are absent. | Official materials said reverting remained possible. Security improves, but Maeve compatibility is not proven. |
| `01.08.01.00` | Last version before Authorization Control according to release-history/community evidence. Direct MQTT is likely legacy behavior, not an official guarantee. | Contemporary Studio/Handy support was expected; long-term compatibility with current apps is not guaranteed. | Supports AMS 2 Pro/HT and fixes a print-quality regression from 01.08.00. Later RFID, communication, drying, PA, and multi-unit fixes are absent. | Officially listed for download. Downgrade may lose settings or require rebinding/calibration; Bambu does not promise preservation. |
| `01.08.00.00` | Pre-Authorization-Control production release according to available evidence; legacy MQTT likely but unguaranteed. | Required then-current Studio/Handy for all features. | First P1 generation with AMS 2 Pro/HT support and new mapping. Community reports describe AMS mapping/start failures. | Officially listed. Superseded quickly by 01.08.01.00 bug fix. Not recommended. |
| Pre-Authorization-Control: `01.07.00.00` | Legacy direct protocols are commonly reported available. | Modern Studio/Handy compatibility is not guaranteed. | Predates official AMS 2 Pro support; therefore unsuitable for Cowboy's two AMS 2 Pro units and drying workflow. | Official historical image is listed, but the security and feature loss is unacceptable. |

Across all downgrade candidates, no official source found during this review guarantees
that settings, calibration, network binding, access code, cloud association, AMS
mapping, or current app sessions survive. No official instruction requires a factory
reset or AMS disconnection for these specific downgrades, but absence of a requirement
is not proof that recovery steps will never be needed.

## Phase 4: decision matrix

| Rank | Option | Genuine telemetry | Reliability / dependency | AMS 2 Pro impact | Security and privacy | Effort / reversibility / print risk | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **A. Official Farm Manager/Fleet status interface** | Documented schema covers all requested fields and camera snapshot | High if the Windows product exposes the supported API; depends on official Bambu server/binding | Schema supports multiple AMS/Pro units and filament fields | Local, authenticated, mTLS in Fleet Hub design; avoids screen scraping | Medium/high. Binding may replace LAN-only mode and affect Studio/Handy. Reversible only with a tested unbind/rebind plan. Never during a print. | **Recommended for an offline feasibility checkpoint, not installation yet** |
| 2 | **E. Remain camera-only** | Camera only; no job telemetry | Current camera path is proven; no Bambu status dependency | None | Smallest new attack surface | Zero implementation effort and fully reversible; no print risk | **Recommended operational state now** |
| 3 | **B. Authorized Bambu Connect integration** | Official UI shows monitoring, but no public consumer telemetry contract was found | Bambu-dependent and signed; suitable for official control/file handoff | Expected to use official printer behavior | Better than raw protocol bypass, but Maeve has no documented least-privilege data interface | Medium; adding software alone does not produce an API | **Hold pending a documented API** |
| 4 | **C. Official cloud read-only telemetry** | Official apps receive it; no public least-privilege Maeve API found | Cloud/account/service dependent | Normal official experience preserved | Would require a private account integration unless Bambu issues a partner credential | High support and credential burden; revocable if a real partner API exists | **Reject private/reverse-engineered cloud access; revisit only with official partner support** |
| 5 | **D. Official firmware downgrade** | Legacy MQTT may provide fields but is not officially guaranteed | Firmware-dependent and exposed to future Studio/Handy incompatibility | Versions before 01.08 lack AMS 2 Pro support; 01.08.x lacks later dual-AMS/drying fixes | Removes later security fixes and broadens local protocol exposure | High risk, disruptive, and rollback may require rebinding/calibration | **Rejected as a telemetry workaround** |

## Exact unresolved questions

1. Does the current free Windows Bambu Farm Manager expose an officially supported,
   documented HTTP API to local third-party clients, or is the published API exclusive
   to the physical Fleet Hub?
2. If an API exists, can a client be issued read-only scope, or do credentials always
   include control endpoints?
3. Does adding this P1S to Farm Manager require leaving LAN-only mode and rebinding to
   farm mode, and exactly what happens to Bambu Studio and Bambu Handy afterward?
4. Does Farm Manager officially support two AMS 2 Pro units on a P1S, including active
   unit/slot, RFID type/color, mapping, and drying state?
5. Is camera access available through Farm Manager's supported interface, and is it a
   snapshot or continuous stream?
6. What are the current Windows Farm Manager license terms, privacy terms, update
   policy, and support boundary for local API consumers?
7. Will Bambu provide a supported partner/read-only path for a single-printer home
   integration without Fleet Hub hardware or farm rebinding?

## Recommended next checkpoint

After all prints finish and Cowboy approves a separate task:

1. Ask Bambu support or the developer-partner channel the unresolved API and binding
   questions above; do not include credentials or private identifiers.
2. If Bambu confirms a supported Windows Farm Manager read-only API, prepare a full
   backup and rollback plan before installing anything.
3. Install only while the printer is idle, but do not bind it until the coexistence and
   rollback gates pass.
4. If binding is later approved, validate Studio, Handy, both AMS 2 Pro units, drying,
   mapping, camera, and ordinary printing before Maeve consumes any status.
5. Give Maeve a read-only adapter that calls only documented GET endpoints, strips
   identifiers, sets `control_capable: false`, and exposes no control methods.
6. If Bambu cannot confirm a supported interface, stop and retain camera-only mode.

## Rollback considerations

- Stop Maeve's proposed adapter before changing any Bambu binding.
- Remove only the new read-only integration credentials and local adapter configuration.
- Unbind Farm Manager/Fleet only through official UI while the printer is idle.
- Restore the prior LAN-only/Developer settings and private local credential through the
  printer and Studio UI if required.
- Verify Studio device status, local camera, both AMS 2 Pro units, slot mapping, drying,
  and a small noncritical print before declaring rollback complete.
- Keep MQTT parked throughout rollback. Do not infer success from camera alone.

## Sources

### Official and primary

- Bambu Lab, Authorization Control announcement:
  https://blog.bambulab.com/firmware-update-introducing-new-authorization-control-system-2/
- Bambu Lab, Bambu Connect and Developer Mode update:
  https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/
- Bambu Lab, Farm Manager introduction and pricing:
  https://blog.bambulab.com/bambu-lab-introduces-local-fleet-control-with-bambu-farm-manager/
- Bambu Lab, P1 firmware download/history listing:
  https://bambulab.cn/zh-cn/support/firmware-download/p1
- Bambu Fleet Hub HTTP API v1.0.0:
  https://portal.bblmw.com/fleet-hub/wb76oog4i8k/files/Bambu%20Fleet%20Hub%20HTTP%20API%20EN%20v1.0.0.pdf
- Bambu Lab official Bambu Studio repository:
  https://github.com/bambulab/BambuStudio

### Secondary/community evidence, not official compatibility proof

- OpenBambuAPI MQTT documentation and issue history:
  https://github.com/Doridian/OpenBambuAPI
- Bambu Studio public issue tracker, network/status reports:
  https://github.com/bambulab/BambuStudio/issues
- Community-maintained P1 release-history mirror:
  https://soporte.trimetra3d.com.ar/hc/guia-trimetra3d/articles/p1-manual-p1p-firmware-release-history

## Validation ledger

| Operation | Count / result |
| --- | --- |
| Printer connection attempts by Codex | 0 |
| MQTT operations | 0 |
| Camera configuration changes | 0 |
| Bambu Studio modifications or UI actions | 0 |
| Firmware downloads | 0 |
| Firmware changes | 0 |
| Printer commands | 0 |
| Rainmeter changes | 0 |
| Maeve production changes | 0 |
| New software installations | 0 |

The active print was not changed, paused, restarted, or interrupted by this work.
