# First P1S Read-Only Connection Checkpoint

Date: 2026-07-31  
Status: **Blocked before authentication — LAN IP not positively identified**  
Branch: `feature/p1s-read-only-telemetry`

## Checkpoint outcome

No authenticated printer connection was attempted. Passive evidence did not map
the physically verified Wi-Fi MAC address to a current LAN IPv4 address. The
restriction against guessing, scanning, or publishing an MQTT request therefore
stopped the live portion of this checkpoint at the correct boundary.

Source-only credential protection was completed and tested with fake secrets.
No real access code was entered, copied, printed, stored, or committed.

## Physically verified identity

| Fact | Verified value |
| --- | --- |
| THS identity | `THS-EQP-000001` |
| Printer name | THS Printer |
| Manufacturer/model | Bambu Lab P1S |
| Model text | `PF001-U` |
| Serial | `01P00C511401400` |
| Wi-Fi MAC | `94:A9:90:21:16:04` |
| Printer network-screen IPv4 | `0.0.0.0` — not usable as an address |
| Router manufacturer | eero |
| Router model | Unknown |
| Router client-list match | Unavailable; account access is currently blocked |

The LAN access code was visible to Cowboy but was deliberately not photographed,
copied, or shared.

## Passive PC-side identification

Only existing local state was inspected. No subnet scan, ping sweep, DNS-SD
query, printer connection, or router change was performed.

- Windows neighbor table: no entry for `94:A9:90:21:16:04`.
- ARP cache: no entry for `94:A9:90:21:16:04`.
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

No live LAN observation was captured because authentication was not permitted
without a positively matched IP, MAC, serial, name, and model.

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

Only fake credentials were used in tests. The real credential has not been
entered because the IP identity gate is still blocked.

Validation results:

- focused P1S credential, telemetry, and launcher tests: 25 passed;
- complete regression suite on disposable databases: 372 passed in 731.200 seconds;
- default real credential file: absent.

## DHCP reservation preview

The reservation cannot yet be safely proposed.

| Required field | Current result |
| --- | --- |
| Verified current P1S IP | Unknown |
| Verified MAC | `94:A9:90:21:16:04` |
| Router make/model | eero / model unknown |
| Router DHCP range | Unknown |
| Recommended reserved IP | Not selected; guessing is prohibited |
| Confirmed safe/available | No — router configuration is unavailable |

No router setting or reservation was changed.

## Exact next checkpoint

1. Restore access to the eero account without sharing credentials with Codex.
2. Read the eero model and DHCP range.
3. Match a connected-device entry to Wi-Fi MAC `94:A9:90:21:16:04`.
4. Confirm that entry shows THS Printer/P1S and record its current IPv4.
5. Recheck the printer screen after it shows a real address rather than `0.0.0.0`.
6. Re-run passive ARP/neighbor comparison and require agreement.
7. Only then use the local masked credential prompt.
8. Run a bounded encrypted subscribe-only capture of
   `device/01P00C511401400/report`, with no publish or push-all request.
9. If the printer sends no report without a publish, disconnect and report that
   technical boundary.
10. Produce a new DHCP reservation preview; do not apply it without separate
    authorization.

## Boundary confirmation

Production PID `58064` was not stopped or restarted. Production port 8787,
database, schema, and records were untouched. No P1S/AMS command, MQTT publish,
authentication attempt, credential entry, router change, DHCP reservation,
persistent telemetry write, deployment, Main change, Financial Headquarters
change, or health-module change occurred.
