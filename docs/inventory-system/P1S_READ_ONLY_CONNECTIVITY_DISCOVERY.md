# P1S Read-Only Connectivity Discovery

**Checkpoint date:** 2026-07-31

**Branch:** `feature/p1s-read-only-telemetry`

**Starting Main commit:** `3caf1c479eedb6a1db61b9f93d80dd7312e34e43`

**Production writes, migrations, service restarts, printer commands, and router changes:** zero

## Decision

Maeve can be prepared for subscribe-only P1S observations without connecting to
the printer yet. This checkpoint adds a brand-neutral read-only adapter
contract, strict external configuration, credential redaction, normalized
telemetry models, fixture parsing, bounded reconnect timing, offline/stale
projections, and a dashboard placeholder that is disabled by default.

Live connectivity is **not complete and is not claimed**. Passive discovery did
not prove the P1S IP address or MAC address. No address was guessed, no subnet
scan was performed, and no credential was accessed.

## Production and runtime safety check

Production was opened only through SQLite read-only URI mode with
`PRAGMA query_only=ON`.

| Check | Result |
|---|---|
| Schema | 19 |
| Integrity / quick check | `ok` / `ok` |
| Foreign-key violations | 0 |
| SHA-256 before/after | `3A9992C0337A11092780AC9F1B5E43126C03509A1EE749CC21679360DF3CFD28` |
| P1S Registry record | Row 1, `THS-EQP-000001`, Bambu Lab P1S |
| Manufacturer serial | `01P00C511401400` |
| Lifecycle / operational | Installed / operating |
| Equipment state version | 2 |
| Equipment telemetry rows | 0 |
| Equipment-to-legacy-printer link | none |
| Existing P1S capabilities | built-in camera, physically verified |

At the initial inspection, port 8787 had exactly one listener: the verified
isolated THS launcher, PID 58064, bound to `127.0.0.1` with the explicit
external production database path. At the final inspection, process ownership
had changed without any action by this checkpoint. The sole listener was PID
60168, launched by parent PowerShell PID 65660 from an older Codex working copy
using `python -m inventory.cli serve` **without** an explicit database.

Read-only process ancestry and source inspection proved that PID 60168 defaults
to that old working copy's `var/inventory.sqlite3`, not the external production
database. That checkout-local database is schema 8, has two active assignments,
and has SHA-256
`C3FF2FD2EA7349448EAD9F8375CAF78782937F481AA625FD630864E3D7FCD8F3`.
The external production database remained schema 19 with its exact accepted
checksum. There was never more than one listener during either observation,
but the current listener is not the verified production service.

This checkpoint did not create, stop, replace, or restart either process. PID
60168 must not be terminated without explicit process-cleanup authorization.
Until it is resolved, port 8787 must not be treated as a production-dashboard
validation endpoint or used for the live P1S checkpoint.

## Existing architecture findings

### Equipment Registry

Migration 018 already provides:

- permanent equipment identity through `equipment_registry`;
- `equipment_printer_links` for a future explicit bridge to the legacy
  `printers` table;
- stable capability records separate from live state;
- `equipment_telemetry_state` keyed by Registry equipment ID;
- freshness fields: `received_at` and `expires_at`;
- device online state, print status, job, progress, remaining time,
  temperatures, observed AMS JSON, errors, warnings, and camera availability;
- `InventoryQueries.equipment_detail()`, which marks expired telemetry stale;
- the `BambuPrinterIntegrationService` protocol seam in `equipment.py`.

The production P1S currently has no telemetry row and no legacy-printer bridge.
Those absences are preserved. This checkpoint does not create either record.

### Printer and production records

The older `printers` table contains manual printer status used by the dashboard.
Print Registry records are committed through a separate controlled
`ProductionService`. A live job name or completion observation therefore does
not become permanent print history. Any future correlation must remain a
proposal handled by the existing `PrintJobCorrelator` seam and a separately
confirmed production workflow.

### Existing live-integration support

No Bambu MQTT client, LAN client, cloud API, polling loop, camera client,
credential loader, or background telemetry worker existed before this
checkpoint. Documentation correctly described Bambu integration as planned.
No third-party MQTT package is currently required by the repository.

## Safe local network discovery

| Fact | Read-only finding |
|---|---|
| Active interface | `Ethernet 2` |
| Adapter | Realtek Gaming 2.5GbE Family Controller |
| PC IPv4 | `192.168.7.8` |
| Prefix | `/22` |
| Local subnet | `192.168.4.0/22` |
| Default gateway | `192.168.4.1` |
| Local IPv4 DNS | `192.168.4.1` |

The existing neighbor cache contained only two unicast client candidates:
`192.168.4.27` and `192.168.4.37`. Neither had a local reverse-DNS result, and
nothing in the passive cache proved that either address belongs to the P1S.
They must not be used as printer addresses without physical/router
confirmation. No address outside the local subnet was queried or scanned.

The repository uses explicit database and loopback listener addresses. It had
no printer-host convention and no Bambu/THS telemetry environment variables.
The new source defines names only; it stores no values.

## Permanent-address recommendation

Use a DHCP reservation in the router. Do not assign an arbitrary static IPv4
address on the printer.

Recommended later procedure:

1. On the P1S screen, open its Network/Wi-Fi information and record the current
   IPv4 and displayed Wi-Fi MAC exactly. Cowboy should compare the serial shown
   there with `01P00C511401400`.
2. Sign in to the router using Cowboy's normal local administration method.
   Do not give the router password to Codex or store it in THS.
3. Find the currently connected device whose exact MAC matches the printer.
   Confirm its current IPv4 and hostname/device label. Do not rely on name or
   manufacturer alone.
4. Review the router DHCP pool. Prefer reserving the printer's current lease,
   or another address the router explicitly reports as available. Do not guess
   an unused address from the `/22` range.
5. Create one MAC-to-IPv4 reservation in the router. Do not enter a manual
   static address on the P1S.
6. Let the lease renew normally or reconnect the printer only in a separately
   approved maintenance window. Confirm the P1S and router show the same IP.
7. Update only the protected local `THS_P1S_HOST` value. Do not put the address
   into equipment identity, migrations, source code, or Git documentation.

Information still required from Cowboy:

- P1S screen's current IPv4;
- exact P1S Wi-Fi MAC from the screen or matching router client record;
- router manufacturer/model and the menu name used for DHCP reservations;
- confirmation whether LAN-only mode is enabled and whether enabling it would
  disrupt Cowboy's current Bambu Studio/cloud workflow;
- confirmation of the chosen reserved address after the router proves it is
  available;
- local entry of the printer access code during the next authorized checkpoint.

## Proposed read-only architecture

```text
P1S LAN report stream
        |
        v
subscribe-only adapter (no publish or command method)
        |
        v
validated/sanitized parser -> in-memory freshness state
        |                              |
        v                              v
P1S dashboard projection       offline/stale/unknown projection

THS inventory queries ------------------------------+
        |                                            |
        +-> separate read-only comparison view <-----+

No arrow exists from observed telemetry to inventory, equipment identity,
AMS assignment, quantity, maintenance, or Print Registry write services.
```

The adapter should connect LAN-locally, subscribe only to the printer report
stream, normalize observations, and automatically reconnect with delays of
1, 2, 4, 8, 16, then at most 30 seconds. A disconnect immediately shows
`offline`; data becomes stale after the configured freshness window. Before
any successful observation, the state is `unknown` and stale.

This checkpoint deliberately does not select or install an MQTT dependency and
does not implement a socket connection. The next checkpoint must review the
chosen library's TLS behavior, subscription-only implementation, license, and
payload compatibility before any credential is entered.

## Security boundary

The protected configuration names are:

- `THS_P1S_TELEMETRY_ENABLED`
- `THS_P1S_HOST`
- `THS_P1S_MQTT_PORT`
- `THS_P1S_SERIAL`
- `THS_P1S_ACCESS_CODE`
- `THS_P1S_STALE_AFTER_SECONDS`

Values must live outside Git and outside the production database, preferably
as account-scoped protected environment/configuration managed by the verified
launcher. No `.env` file should be created in the repository. The access code
must never be printed, included in exception text, HTTP output, telemetry rows,
audit details, screenshots, reports, or process arguments.

Important limitation: a Bambu LAN access credential may authorize more than
read-only operations at the printer. Least privilege must therefore be enforced
by Maeve's code boundary: subscribe only, provide no publish API, construct no
command topics/payloads, and run no control-capable dependency wrapper. Network
segmentation or a future printer-side read-only credential would strengthen
this boundary if Bambu supports it.

The dashboard flag defaults to disabled. When disabled, `/integrations/p1s`
returns 404 and no navigation link appears. Enabling only the display flag
shows an explicit `Offline / unknown` placeholder; it does not connect to the
printer or write the database.

## Telemetry, inventory truth, and derived comparison

| Category | Examples | Authority and behavior |
|---|---|---|
| Live printer telemetry | online state, printer state, job, progress, remaining time, layers, temperatures, observed AMS/slot, reported material/color, errors/warnings, update time | Ephemeral device observation; freshness labeled; never authoritative inventory |
| THS inventory truth | permanent spool IDs, seven assignments, empty/restricted A2, quantities, catalog color/type, equipment relationships | Controlled database workflows only; telemetry cannot change it |
| Derived comparison | observed AMS slot versus recorded assignment, observed type/color versus catalog truth | Read-only warning/proposal; mismatch never self-corrects either source |

The initial source model covers every requested display field. The existing
schema can store most fields, with AMS observations in JSON, but it has no
dedicated current-layer or total-layer columns. This checkpoint uses in-memory
models only. If durable layer persistence is later required, it needs a
separately reviewed additive migration; raw payloads must not be stuffed into
unrelated fields.

## Source foundation added

- `inventory/telemetry.py`
  - external configuration validation;
  - secret-safe summaries and recursive log redaction;
  - subscribe-only adapter protocol;
  - neutral P1S telemetry projection;
  - conservative Bambu report parser;
  - bounded reconnect policy;
  - offline, unknown, and stale projections.
- `tests/fixtures/bambu_p1s_status.json`
  - synthetic status fixture with no real credential, IP, serial, or job secret.
- `tests/test_p1s_telemetry.py`
  - configuration, redaction, parser, validation, stale/offline, reconnect,
    read-only contract, feature-gate, and zero-write dashboard coverage.
- `inventory/web.py`
  - disabled-by-default P1S status placeholder and conditional navigation.

No schema, migration, dependency, runtime launcher, production service, health
module, inventory service, maintenance service, or printer-control code changed.

## Validation

- Python syntax compilation passed for the telemetry and dashboard modules.
- Focused telemetry, Equipment Registry, launcher, and dashboard suite:
  **65 passed** in 97.469 seconds.
- Complete regression suite: **362 passed** in 706.460 seconds.
- All tests used disposable databases and synthetic/mock data.
- The production checksum remained unchanged after testing.

## Risks

- The exact Bambu LAN report contract must be verified against an authenticated
  read-only session; fixture keys are a conservative adapter boundary, not a
  claim of current printer compatibility.
- Firmware may change field names, report frequency, TLS behavior, or LAN/cloud
  operating rules.
- A printer access code may technically allow control even though Maeve exposes
  no command surface.
- DHCP addresses can change until a reservation is made.
- Passive caches cannot prove device identity. MAC, IP, and serial must be
  matched physically and in the router.
- AMS telemetry can be delayed, incomplete, or disagree with physical THS
  inventory; disagreement must surface as a warning, never an automatic write.
- The existing telemetry table is a current-state projection, not immutable raw
  telemetry history. Retention/history requires a separate design decision.
- Port 8787 is currently owned by an unverified old-worktree server using a
  schema-8 checkout-local database. This does not change production data, but it
  can display stale/wrong shop state and blocks live-integration validation.

## Rollback

The feature is disabled by default and makes no schema or production changes.
Before merge, rollback is deleting the feature branch or reverting its commits.
After a future merge, revert the source commit normally without rewriting Git
history. No database restore, printer reset, router change, or inventory
correction is needed for this checkpoint.

## Exact next checkpoint

**P1S Read-Only Connectivity Checkpoint 2: physically verified address and
credential-local authenticated observation.**

That checkpoint should require explicit approval and then:

1. separately authorize verification and graceful cleanup of PID 60168, then
   restore only the verified production launcher and prove its explicit
   database path and sole listener ownership;
2. physically confirm P1S IPv4, MAC, serial, LAN-only/cloud mode, and router
   reservation plan;
3. review and add one MQTT/TLS dependency if justified;
4. enter the access code locally without displaying or committing it;
5. connect to the verified P1S address and subscribe only;
6. capture a sanitized field-coverage report with no raw secrets;
7. prove no publish/control path exists and no database writes occur;
8. compare observed AMS data read-only with THS assignments;
9. stop before DHCP reservation, persistent telemetry writes, deployment, or
   any printer/inventory command.

An authenticated connection must not be claimed until that separately approved
checkpoint completes successfully.
