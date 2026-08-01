# P1S MQTT Authentication Diagnosis

Date: 2026-07-31  
Checkpoint type: source-only and documentation-only  
Branch: `feature/p1s-read-only-telemetry`

## Conclusion

The THS client's basic MQTT wire format matches the well-established local P1S
protocol. The most likely cause of the two pre-subscription rejections is the
printer's newer Authorization Control operating mode: firmware `01.10.00.00`
may require LAN Only plus Developer Mode before a raw third-party MQTT client is
authorized. This is a diagnosis, not permission to change either setting.

The previous client collapsed every non-zero MQTT CONNACK into one message, so
the historical attempts do not prove whether the printer returned code 4
(username/password rejected) or code 5 (client not authorized). The source-only
repair preserves and sanitizes that distinction for a future authorized test.

## Proven facts

- Printer: THS Printer, Bambu Lab P1S / `PF001-U`.
- Serial: `01P00C511401400`.
- Firmware: `01.10.00.00`.
- Network identity: `192.168.5.226` resolved by Windows to
  `94:A9:90:21:16:04`, matching the printer and eero Max 7.
- TCP/TLS reached the printer twice on port 8883.
- The printer returned MQTT CONNACK with a non-zero result before SUBSCRIBE.
- The old diagnostic discarded the exact CONNACK return code.
- The protected access code was privately entered twice on the second attempt;
  its value was never exposed.
- No MQTT PUBLISH, request topic, push-all request, printer command, telemetry
  write, or production change occurred.

## Protocol comparison

| Item | THS implementation | Evidence and assessment |
| --- | --- | --- |
| Port | 8883 | Matches established local Bambu MQTT-over-TLS references. |
| Encryption | TLS client session; local certificate not CA-verified | Matches established local integrations using the printer's local certificate. Encryption succeeded twice. |
| MQTT version | MQTT 3.1.1 (`MQTT`, level 4) | Matches established clients; now maps CONNACK code 1 separately if rejected. |
| Username | `bblp` | Matches established local-mode integrations. |
| Password | Protected printer access code, unchanged bytes | Matches established local-mode integrations. Never logged or placed in arguments. |
| Client ID | `ths-readonly-` plus final six serial characters | Valid MQTT 3.1.1 identifier. Community clients use arbitrary unique IDs; no evidence Bambu requires an official client ID. |
| Report topic | `device/01P00C511401400/report` | Matches established reverse-engineered report topic. |
| Request topic | Never constructed or used | Required THS safety boundary. |
| Publish | No publish implementation | Proven by synthetic packet tests. |

Official Bambu documentation publicly confirms that Authorization Control was
introduced for printer connections and that monitoring/status remains a
supported class of behavior. Bambu's follow-up describes Standard Mode with an
authorization process and an optional Developer Mode for P1/P1S users who need
MQTT, live stream, and FTP available to custom integrations:

- https://blog.bambulab.com/firmware-update-introducing-new-authorization-control-system-2/
- https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/
- https://cdn1.bambulab.com/trust-center/file/bambulab-security-whitepaper-en.pdf

Official material does not publicly document the raw MQTT authentication wire
contract or a firmware-`01.10.00.00` CONNACK matrix. Bambu directs integration
developers to its partner channel for those technical details. Therefore the
port, username, password, client-ID flexibility, and topic conclusions above are
explicitly based on mature community/reverse-engineered references, including:

- https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- https://www.openhab.org/addons/bindings/bambulab/

## Ranked likely causes

1. **Developer Mode is not enabled under LAN Only Mode — high confidence.**
   Official Bambu material says Developer Mode for P1-series custom solutions
   leaves MQTT available outside Authorization Control. The printer is currently
   cloud-bound in Bambu Studio, which is consistent with LAN Only being off.
2. **Current access code is not the credential accepted by this operating mode —
   medium confidence.** Two careful private entries reduce ordinary typing risk,
   but without the historical CONNACK code the diagnosis cannot distinguish a
   stale/wrong code (code 4) from an authorization policy refusal (code 5).
3. **Firmware-specific client authorization — medium confidence.** Firmware
   `01.10.00.00` is newer than Bambu's Authorization Control announcement. The
   public documentation does not expose its exact raw-client rules.
4. **Client identifier rejected — low confidence.** The ID is valid MQTT 3.1.1
   and community clients commonly use arbitrary unique IDs. A future code-2
   diagnostic would prove this case.
5. **Protocol version mismatch — low confidence.** MQTT 3.1.1 is the established
   protocol. A future code-1 diagnostic would prove otherwise.

## Causes ruled out or substantially reduced

- Wrong IP or wrong physical printer: ruled out by screen, eero, and PC MAC
  agreement.
- Broker port unavailable: ruled out by two successful TCP/TLS handshakes.
- TLS negotiation failure: ruled out for the historical attempts.
- Wrong report topic: cannot cause a rejection before SUBSCRIBE.
- A prohibited publish/request: ruled out by source inspection and packet tests.
- Production database or dashboard interaction: not involved.

## Improved sanitized diagnostics

Future synthetic and authorized live runs can now report only these categories:

- `tls_failure`;
- `rejected_username_password` (MQTT code 4);
- `unauthorized_client` (MQTT code 5);
- `unsupported_protocol_version` (MQTT code 1);
- `client_identifier_rejected` (MQTT code 2);
- `broker_unavailable` (connection failure or MQTT code 3);
- `timeout`;
- `subscription_rejected`;
- `connection_lost` or `protocol_error`.

The safe result includes category, sanitized message, and numeric MQTT return
code only. It never includes host credentials, credential length, credential
hash, packet payloads, or exception details that could contain secrets.

## Cowboy's read-only screen inspection

Do not change any toggle and do not photograph or share the access code.

1. Wake the P1S and press the **gear / Settings** button.
2. Open **WLAN** or **Network**.
3. Confirm the connected Wi-Fi name and IPv4 `192.168.5.226`.
4. Confirm the displayed MAC remains `94:A9:90:21:16:04`.
5. Locate **LAN Only Mode** and report only `On` or `Off`. Do not touch it.
6. Scroll down within the same WLAN screen. Locate **Developer Mode** or a
   similarly named local/developer-access option. Report `On`, `Off`, or
   `Not shown`. Do not touch it. On newer firmware it may appear only when LAN
   Only Mode is enabled.
7. Locate the **Access Code** row. Confirm only that a code is present and that
   it is the code used for the private entry. Do not read it aloud, photograph
   it, refresh/rotate it, or send it anywhere.
8. Return to **Settings**, open **Device**, **General**, or **Firmware** (label
   varies), and confirm firmware `01.10.00.00` and serial
   `01P00C511401400`.
9. Exit without saving or changing anything.

The only requested reply is:

```text
LAN Only Mode: On / Off
Developer Mode: On / Off / Not shown
Local network access option: On / Off / Not shown
Access code present and privately rechecked: Yes / No
Firmware still 01.10.00.00: Yes / No
IP and MAC still match: Yes / No
```

## Proposed repair

Do not re-enter the credential again yet. First inspect the settings above.

- If LAN Only is off and Developer Mode is absent/off, the recommended repair is
  a separately authorized maintenance window to enable LAN Only and then
  Developer Mode, followed by one bounded subscribe-only test.
- If both modes are already on, do not toggle them. The next repair is to capture
  the new sanitized CONNACK category once, then decide whether credential
  rotation/re-entry or a client-ID adjustment is justified.
- If the screen exposes a separate local-network-access toggle, document its
  exact label/state before deciding anything.

No authentication assumption will be changed solely from speculation.

## Effects requiring separate authorization

Enabling LAN Only Mode disconnects the printer from Bambu cloud services. This
can disable or disrupt Bambu Handy, cloud printing, remote monitoring, remote
camera access, MakerWorld-to-printer workflows, and the current cloud-bound
Bambu Studio connection. Bambu Studio can operate locally after a separate LAN
binding, but that is a workflow change.

Developer Mode deliberately relaxes Authorization Control for local MQTT, live
stream, and FTP. Official Bambu material says the user assumes responsibility
for local-network security and Bambu support may not cover that mode.

These effects are material. Neither mode may be changed without Cowboy's
separate explicit authorization and a rollback plan.

## Exact next live-test procedure

Only after settings inspection and separate authorization:

1. Confirm production and Git safety gates.
2. Confirm printer IP/MAC/serial agreement again.
3. Confirm the DPAPI credential is present/decryptable without revealing it.
4. Apply only the separately approved printer-mode change, if any.
5. Reconfirm Bambu Studio/Handy expected availability for that mode.
6. Run one 20-second encrypted MQTT 3.1.1 attempt.
7. Send CONNECT, then subscribe only to
   `device/01P00C511401400/report` if CONNACK succeeds.
8. Never publish or use `/request`; do not send push-all.
9. Record only the sanitized category/code or normalized observation.
10. Disconnect cleanly and verify zero production writes.

## Rollback procedure

If a future authorized LAN/Developer change disrupts required workflows:

1. Stop the THS test client and verify it is disconnected.
2. Disable Developer Mode.
3. Disable LAN Only Mode to restore cloud operation.
4. Reconnect/rebind Bambu Studio and Bambu Handy only through their normal UI if
   required; do not expose the access code.
5. Verify cloud status, remote monitoring, and camera behavior.
6. Reconfirm the printer's new IP/MAC mapping if DHCP changed.
7. Do not delete audit/report history; record the observed rollback result.

Source rollback is a normal Git revert of this checkpoint commit. The production
database needs no rollback because this checkpoint performs no production write.

## Validation

- Focused P1S MQTT, credential, telemetry, and launcher tests: 31 passed.
- Complete regression suite on disposable databases: 378 passed in 679.309 seconds.
- Synthetic packet sequence: CONNECT, SUBSCRIBE, DISCONNECT; zero PUBLISH.
- Production checksum and service verification are recorded at checkpoint close.

## Boundary confirmation

No live MQTT connection or credential re-entry occurred during this diagnosis.
No printer/router setting, DHCP reservation, production data/schema/service,
inventory, Financial Headquarters, health module, deployment, or Main change was
made.
