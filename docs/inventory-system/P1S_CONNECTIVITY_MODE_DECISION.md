# P1S Connectivity-Mode Decision Checkpoint

Date: 2026-07-31  
Checkpoint type: zero-change decision and documentation  
Branch: `feature/p1s-read-only-telemetry`

## Recommendation

Keep the P1S in its current cloud-bound configuration and postpone Maeve's live
telemetry connection. Retain the completed identity, credential-protection,
subscribe-only client, sanitized diagnostics, telemetry normalization, and
synthetic-test foundations offline.

This is the safest choice that preserves Cowboy's normal Bambu Studio and Bambu
Handy experience. There is no documented, supported, public read-only API that
gives Maeve the required live P1S status while keeping the present cloud-bound
workflow unchanged. A reverse-engineered Bambu cloud connection would require a
broader cloud-account credential, depend on a private service, and be less safe
and less stable than the deliberately bounded local client.

No setting or connection was changed during this checkpoint.

## Current unlocked observation — 2026-08-20

| Fact | Observation |
| --- | --- |
| Observed P1S IP | Private local value omitted from Git |
| LAN Mode observed | `OFF` |
| DHCP reservation | `NOT YET COMPLETED` |
| Status | `CURRENT OBSERVATION, NOT LOCKED` |

This temporary address is documentation only. It is not an authoritative
configuration value and must not be used to activate telemetry. The printer
remains cloud-bound through Bambu Studio.

## Current proven state

| Fact | Value |
| --- | --- |
| Printer | THS Printer, Bambu Lab P1S / `PF001-U` |
| Serial | `01P00C511401400` |
| Firmware | `01.10.00.00` |
| IPv4 | Matching private local value verified on printer and router |
| Wi-Fi MAC | `94:A9:90:21:16:04` on both printer and eero |
| LAN Only Mode | Off |
| Developer Mode | Not shown |
| Local-network-access option | Not shown |
| Access code | Present and privately rechecked; value not accessed here |
| Previous connection result | TLS reached the printer; MQTT authentication was rejected before subscription |

The exact IP/MAC agreement rules out mistaken printer identity. Reaching TLS and
receiving an MQTT rejection substantially rules out routing, port, and TLS as the
cause. The remaining high-confidence issue is authorization policy for a raw
third-party client in the printer's current mode.

## Evidence boundaries

Bambu's official security material describes cloud-connected operation, LAN
Only Mode, the newer authorization controls, and optional Developer Mode. It
states that LAN Only stops cloud connectivity and that Developer Mode removes
the newer authorization control from local MQTTS. Bambu also says the user
assumes local-network security responsibility and that those raw protocols are
not officially supported.

Bambu does not publish the raw P1S MQTT contract or a public read-only cloud API
for this Maeve use case. Statements about raw MQTT topics, cloud MQTT, or
third-party clients are therefore identified below as reverse-engineered rather
than official.

Primary sources:

- Bambu Lab, "Updates and Third-Party Integration with Bambu Connect":
  https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/
- Bambu Lab, "Firmware Update Introducing New Authorization Control System":
  https://blog.bambulab.com/firmware-update-introducing-new-authorization-control-system-2/
- Bambu Lab Security White Paper, September 2025:
  https://cdn1.bambulab.com/trust-center/file/bambulab-security-whitepaper-en.pdf

Established reverse-engineered reference used only to characterize alternatives:

- OpenBambuAPI MQTT notes:
  https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md

## Option comparison

| Decision area | 1. LAN Only + Developer Mode | 2. Cloud-bound alternative | 3. Postpone live telemetry |
| --- | --- | --- | --- |
| Bambu Studio locally | Intended to work after a new LAN/access-code binding on the same network. Connection discovery or rebinding may be required. | Continues exactly as it does now through the supported Bambu workflow. | Continues exactly as it does now. |
| Bambu Handy at home | Not available for the LAN-Only printer through the normal supported workflow. | Continues normally. | Continues normally. |
| Bambu Handy away from home | Not available because the printer is disconnected from Bambu cloud. | Continues normally. | Continues normally. |
| Cloud printing / MakerWorld | Disabled for the printer in LAN Only Mode. Local Studio sending remains the intended path. | Continues normally. | Continues normally. |
| Remote camera and monitoring | Cloud/remote access is lost. A local third-party stream may be technically available in Developer Mode, but is unsupported and is not part of the THS client. | Official Bambu camera and monitoring continue. No safe supported Maeve feed was identified. | Official Bambu camera and monitoring continue; Maeve shows no live feed. |
| Security | Printer stops using Bambu cloud, but Developer Mode deliberately exposes local MQTT, live stream, and FTP outside Authorization Control. Network isolation and trusted-LAN hygiene become Cowboy's responsibility. | Official Bambu authorization remains. Reverse-engineered cloud access would add a high-value account credential and private-cloud dependency, so it is not recommended. | Smallest additional attack surface: no Maeve connection and no new credential use. |
| Reliability for Maeve | Best available direct local path once authorized, but unsupported and dependent on local Wi-Fi, DHCP identity, firmware behavior, and relaxed local access. | Official apps are reliable for Cowboy; no supported automation interface exists for Maeve. Screen/log scraping is brittle; reverse-engineered cloud MQTT can change without notice. | Offline fixtures, parsing, freshness rules, and UI contracts remain deterministic; live availability is intentionally absent. |
| Credential requirement | The printer's LAN access code, kept DPAPI-protected and used only in process memory. | Official apps retain their normal Bambu account session. Reverse-engineered cloud access would require a Bambu account token/identifier and is rejected for THS use. | No credential is read or used. Existing protected value may remain untouched. |
| Support status | LAN Only and its toggle are official. Developer Mode is an official opt-in, but Bambu states the exposed MQTT/live-stream/FTP protocols are not officially supported. The THS MQTT contract is reverse-engineered. | Bambu Studio/Handy are official. Automated Studio/log scraping and direct cloud MQTT are reverse-engineered or unsupported; no public supported Maeve telemetry API was identified. | Fully within THS control; no claim of live Bambu integration. |
| Normal workflow preserved | No. It materially changes Handy, cloud printing, and remote access. | Yes for official apps, but a safe direct Maeve feed is not presently available. | Yes. |
| Overall decision | Viable only if Cowboy later accepts the cloud/Handy tradeoff and local-network risk. | Keep official applications, but do not attach Maeve through a reverse-engineered cloud shortcut. | **Recommended now.** |

## Option 1: LAN Only plus Developer Mode

### What it accomplishes

This is the most plausible path to the existing local subscribe-only THS client.
Bambu's official material says Developer Mode leaves MQTTS available outside the
new Authorization Control. It does not make the raw MQTT protocol officially
supported.

### Future activation procedure (requires separate approval)

Do not perform these steps during an active print.

1. Wait until the printer is idle and physically attended.
2. Confirm Bambu Studio and Handy work normally; save any active Studio project.
3. Record only the current firmware, serial, IP, MAC, and toggle states. Do not
   copy the access code into notes or chat.
4. On the P1S, open **Settings (gear) > WLAN / Network**.
5. Enable **LAN Only Mode** and acknowledge that cloud service will be lost.
6. Reopen or scroll the network page; enable **Developer Mode** if it appears.
7. In Bambu Studio on the same local network, select/add the printer using its
   LAN binding flow. Enter the access code only in Bambu Studio's protected UI.
8. Confirm a harmless Device-page connection before any THS test.
9. Under a second explicit authorization, revalidate IP/MAC, then perform one
   bounded subscribe-only THS attempt with no publish or request topic.
10. Stop immediately if the printer, Studio, or AMS state differs from the
    recorded baseline.

Menu labels may vary with firmware. The absence of Developer Mode while LAN Only
is off is consistent with Bambu's mode design; it must not be inferred as a
missing printer feature without observing the authorized LAN-only screen.

### Rollback

1. Disconnect and stop the THS client.
2. While the printer is idle, disable **Developer Mode**.
3. Disable **LAN Only Mode**.
4. Restore the printer's ordinary Bambu account/cloud binding through Bambu
   Studio or Bambu Handy if prompted.
5. Verify Studio device control, Handy both on local Wi-Fi and cellular data,
   cloud printing, remote camera, print history, and AMS display.
6. Reconfirm IP/MAC because DHCP may assign a different address.

Switching back is intended to restore cloud operation, but the printer or apps
may require sign-in/rebinding and fresh discovery. Restoration must be verified;
it should not be promised as instantaneous or session-preserving.

### Print and configuration risk

Changing connectivity mode is not expected to erase printer files, AMS
configuration, calibration, or firmware, and it does not install firmware.
However, it can interrupt monitoring, camera, remote control, file transfer,
cloud association, and Studio/Handy visibility. For that reason, never toggle it
during an active print. Photographing or exporting the access-code screen is
prohibited.

## Option 2: retain cloud-bound operation and seek an alternative

### Safe supported position

Keep using Bambu Studio and Bambu Handy as designed. This preserves local and
remote control, cloud printing, remote monitoring, and camera access. It does
not provide Maeve a supported machine-readable telemetry interface.

The following are not approved substitutes:

- **Reverse-engineered Bambu cloud MQTT:** may expose a broader account token,
  depends on private cloud behavior, and is not a published supported API.
- **Impersonating an official Bambu client or bypassing authorization:** unsafe,
  unsupported, and outside THS scope.
- **Scraping Bambu Studio UI, private configuration, logs, or camera output:**
  brittle, may expose credentials, and cannot provide a trustworthy telemetry
  contract.
- **Polling printer ports again in cloud-bound mode:** repeats the already
  rejected path and is prohibited without a new decision.

If Bambu later publishes a documented read-only local/cloud API or grants THS an
official partner integration, reassess it as a new checkpoint. Until then,
"keep cloud-bound" and "give Maeve a safe supported live feed" cannot both be
claimed.

### Activation and rollback

No activation is required: leave all printer/router settings and official apps
unchanged. If a future official API becomes available, use a separate source-
only review, least-privilege credential plan, synthetic tests, and one bounded
read-only pilot. Rollback would revoke that integration credential and remove
only its local configuration. No printer mode change should be bundled into it.

There is no active-print, AMS, calibration, file, or firmware risk from the
recommended no-change form of this option.

## Option 3: postpone live telemetry

### Retained foundation

- permanent Registry identity `THS-EQP-000001` and verified serial;
- exact network-identity gate using IP and MAC;
- DPAPI-protected local credential storage outside Git;
- a bounded subscribe-only client with no publish implementation;
- sanitized MQTT/TLS failure categories;
- normalized telemetry and freshness-aware projection contracts;
- synthetic-broker and captured-fixture tests;
- separation between observations and authoritative equipment, AMS, inventory,
  assignment, maintenance, and production records.

Maeve should display telemetry as unavailable/not connected, never fabricate a
live value from inventory or stale fixtures, and never change authoritative
records from an observation.

### Activation and rollback

No activation is required. Do not start the live connector and do not read the
protected credential. Continue source development only against synthetic data.
To resume later, open a new decision checkpoint using current official Bambu
documentation and firmware behavior. To roll back the offline foundation, use a
normal Git revert; production and the printer require no rollback.

This option causes no active-print, AMS, calibration, file, firmware, cloud,
camera, or remote-monitoring change.

## Decision gate for any future live attempt

A new live attempt requires Cowboy to choose and explicitly authorize one of:

1. accept LAN Only + Developer Mode tradeoffs and schedule an idle-printer
   maintenance window; or
2. approve a newly documented official read-only integration after its security
   and workflow effects are reviewed.

Neither condition exists today. Credential re-entry, MQTT retry, DHCP
reservation, router changes, and printer-mode changes remain prohibited.

## Validation and boundary

This checkpoint adds documentation only; it adds no decision logic and therefore
requires no new decision-logic test. Existing P1S focused tests and the complete
regression suite are rerun to prove the branch remains healthy.

- Focused P1S MQTT, credential, telemetry, and launcher tests: 31 passed in
  2.607 seconds.
- Complete regression suite on disposable databases: 378 passed in 689.130
  seconds.
- No live network test, protected-credential read, or production route/database
  check was performed.

No printer or router setting, live connection, protected credential, production
data/schema/service, deployment, DHCP reservation, inventory, Financial
Headquarters, health module, or Main branch was changed.

## Final phase decision and parked status

Decision recorded: 2026-07-31
Status: **Parked — preserved for a safe future restart, not abandoned**

Cowboy's final decision for this phase is:

- keep the P1S cloud-bound;
- keep LAN Only Mode off;
- do not enable Developer Mode;
- preserve Bambu Studio, Bambu Handy, cloud printing, remote camera access, and
  remote monitoring;
- postpone Maeve live P1S telemetry until a safe cloud-compatible method is
  available.

The feature branch and its complete history remain preserved at
`feature/p1s-read-only-telemetry`. They are deliberately not merged into Main.
The protected credential remains outside Git and must not be accessed, tested,
replaced, or removed as part of parking this work.

### Exact future restart point

Restart only in a new, separately authorized checkpoint from the then-current
tip of `feature/p1s-read-only-telemetry`. Begin with a source-only review of the
latest official Bambu integration and security documentation. Do not begin with
a live connection or credential check.

The restart checkpoint must first revalidate:

1. Cowboy still wants live P1S telemetry without sacrificing the normal Bambu
   Studio, Bambu Handy, cloud-printing, camera, and remote-monitoring workflow.
2. Bambu now provides a documented cloud-compatible, read-only integration, or
   an officially approved partner method suitable for Maeve.
3. The method does not require client impersonation, private-cloud protocol
   bypass, LAN Only Mode, Developer Mode, MQTT publishing, or printer commands.
4. Credential scope, storage, rotation, revocation, logs, and failure handling
   have a reviewed least-privilege design. The existing protected access code
   is not read merely to perform this review.
5. Current printer model, serial, firmware, IP, MAC, cloud binding, and network
   mode are physically and passively reverified before any later live pilot.
6. The offline adapter, telemetry normalization, freshness rules, synthetic
   broker tests, and zero-authoritative-write guarantees still pass on the
   current codebase.
7. A bounded zero-publish test plan, rollback plan, and explicit Cowboy
   authorization exist before the first live attempt.

If no safe cloud-compatible method exists, leave this branch parked and make no
connection attempt.

### Separation from the next Maeve checkpoint

The next Maeve project checkpoint starts separately from current `origin/main`,
not from this parked telemetry branch. Its scope returns to the original Maeve
plan: core dashboard, inventory integration, briefings, calendar, weather,
reminders, Raspberry Pi runtime, and hardware planning. P1S live telemetry must
not be silently carried into that work.
