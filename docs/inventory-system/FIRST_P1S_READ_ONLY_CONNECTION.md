# First P1S Read-Only Connection Checkpoint

Date: 2026-07-31  
Status: **Blocked at MQTT authentication — no subscription established**
Branch: `feature/p1s-read-only-telemetry`

## Checkpoint outcome

After an eero restart, the printer screen, eero client record, and PC neighbor
resolution all agreed on the P1S identity. Two bounded encrypted MQTT connection
attempts reached the printer, but the printer rejected the protected MQTT session
before subscription. The second attempt followed a fresh private re-entry of the
access code. No further retry was made.

Source-only credential protection and a subscribe-only client were completed and
tested with fake secrets and a synthetic broker. The real access code was entered
only through the masked local prompt and remains DPAPI-protected outside Git. It
was never copied, printed, logged, documented, or placed in a command line.

## Physically verified identity

| Fact | Verified value |
| --- | --- |
| THS identity | `THS-EQP-000001` |
| Printer name | THS Printer |
| Manufacturer/model | Bambu Lab P1S |
| Model text | `PF001-U` |
| Serial | `01P00C511401400` |
| Wi-Fi MAC | `94:A9:90:21:16:04` |
| Printer network-screen IPv4 | `192.168.5.226` |
| eero client IPv4 | `192.168.5.226` |
| Router manufacturer | eero |
| Router model | eero Max 7 |
| Router client-list match | Yes; exact IP and MAC agreement |
| Connection reported by eero | Living Room eero, 2.4 GHz, WPA3 |

The LAN access code was visible to Cowboy but was deliberately not photographed,
copied, or shared.

## Passive PC-side identification

Only existing local state was inspected. No subnet scan, ping sweep, DNS-SD
query, printer connection, or router change was performed.

- A single-address reachability check to `192.168.5.226` succeeded.
- Windows resolved `192.168.5.226` to `94:A9:90:21:16:04` on `Ethernet 2`.
- Windows DNS cache: no Bambu, P1S, or THS Printer identity record.
- PC address remained `192.168.7.8/22`; gateway remained `192.168.4.1`.
- Bambu Studio visibly showed `THS Printer` and current Device/AMS status.
- Bambu Studio PID `63924` had one established MQTT connection to a public cloud
  address on port 8883 and no established private-LAN printer connection.
- Existing private neighbor entries did not contain the verified printer MAC.

Reading hidden Bambu Studio configuration was rejected because those files may
contain credentials. No workaround was attempted. Visible UI inspection was used
instead and did not reveal a LAN address.

## Live observed telemetry

No live report was captured. Identity was positively matched, TLS connected, and
the client sent an MQTT CONNECT packet. The printer rejected the MQTT session,
so the client never established the report subscription.

Two attempts were made: the initial protected credential and one careful private
replacement. Both were rejected. Each client closed cleanly. No MQTT PUBLISH,
`/request` topic, push-all request, or printer/AMS command was sent.

All requested live fields remain **Unknown** for this checkpoint:

- online/offline state through the THS adapter;
- printer state and current job;
- progress, remaining time, and layers;
- nozzle and bed temperatures;
- active AMS and slot;
- observed filament type and color;
- warning and error state;
- observation time and freshness.

The values visible inside Bambu Studio were not claimed as a THS authenticated
capture and were not persisted.

## THS inventory truth and comparison

Production remained schema 19 with checksum
`3A9992C0337A11092780AC9F1B5E43126C03509A1EE749CC21679360DF3CFD28`.
The authoritative Equipment Registry identity remains `THS-EQP-000001` with
serial `01P00C511401400`. No inventory, AMS assignment, equipment, maintenance,
parts, telemetry, or audit row was changed.

There is no derived live-versus-inventory comparison because there was no
authenticated LAN observation. Missing evidence was not converted into facts.

## Protected local credential method

`scripts/p1s_credential.py` provides two actions:

- `set`: uses a private masked prompt twice; the secret is never a command-line
  argument or normal console output;
- `status`: reports only present/missing, current-user decryptability, and the
  local path.

The default store is outside Git at:

`%LOCALAPPDATA%\THS-Command-Center\secrets\p1s-access-code.dpapi`

The access code is encrypted with Windows DPAPI for the current Windows user.
The file ACL is restricted to that identity and SYSTEM. Git ignores DPAPI files
as a second defense. Telemetry configuration can load the code directly from
the protected store without placing it in a command-line argument or report.

The real credential is present only in the external DPAPI store and decrypts for
Cowboy's Windows account. The file ACL grants access only to Cowboy and SYSTEM.

Validation results:

- focused subscribe-only, credential, and telemetry tests: 17 passed;
- complete regression suite: 374 passed in 699.341 seconds;
- protected real credential file: present and current-user decryptable;
- fake-broker proof: CONNECT, report SUBSCRIBE, and DISCONNECT only; zero PUBLISH.

## DHCP reservation preview

The reservation cannot yet be safely proposed.

| Required field | Current result |
| --- | --- |
| Verified current P1S IP | `192.168.5.226` |
| Verified MAC | `94:A9:90:21:16:04` |
| Router make/model | eero / eero Max 7 |
| Router DHCP range | Unknown |
| Recommended reserved IP | `192.168.5.226`, contingent on eero range/availability validation |
| Confirmed safe/available | No — router configuration is unavailable |

No router setting or reservation was changed.

## Exact next checkpoint

1. On the P1S, verify the displayed LAN access code and whether local/LAN access
   is enabled; do not share the code in chat.
2. Determine whether current P1S firmware requires an additional local-access
   setting before MQTT authentication is accepted.
3. Do not retry authentication until that setting boundary is understood.
4. Once authorized, use the existing protected credential and repeat one bounded
   encrypted subscribe-only capture of `device/01P00C511401400/report`.
5. If authentication succeeds but no natural report arrives, disconnect rather
   than publish a push-all request.
6. Confirm the eero DHCP range and reservation availability, then produce a final
   reservation preview. Do not apply it without separate authorization.

## Boundary confirmation

Production PID `58064` was not stopped or restarted. Production port 8787,
database, schema, and records were untouched. No P1S/AMS command, MQTT publish,
authentication attempt, credential entry, router change, DHCP reservation,
persistent telemetry write, deployment, Main change, Financial Headquarters
change, or health-module change occurred.
