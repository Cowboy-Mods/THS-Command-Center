# Maeve Live Monitoring Checkpoint

Date: 2026-08-22

## Outcome

Maeve is a working, private, monitoring-only P1S companion. The live path is:

1. Bambu Farm Manager receives printer and AMS state on the local network.
2. Maeve's local bridge selects the exact printer page and converts the response
   to a strict sanitized telemetry model.
3. Rainmeter Print Watch and Maeve Command Console read only that sanitized model.
4. Tailscale Serve makes the loopback-only console available to authenticated
   devices in Cowboy's private tailnet without exposing Maeve or the printer to
   the public internet.

No printer-control method is exposed by Maeve. `control_capable` remains false.

## Working capabilities

- Current printer state, job, progress, remaining time, layer count, nozzle and
  bed temperatures, sanitized warnings, and data age.
- Read-only AMS inventory for both units, including slot, material, color,
  remaining level when reported, and humidity. Active slot remains "not
  reported" when Farm Manager does not provide an unambiguous selector.
- Factory-camera viewing through a local on-demand adapter with a one-viewer
  limit and inactivity release.
- Desktop Rainmeter Print Watch and a responsive phone-first Command Console.
- Installable iPhone Home Screen web app over private HTTPS.
- Foreground alerts while the app is open.
- Protected background Web Push with generic, non-sensitive messages only.
- Duplicate-suppressed alerts for first-layer completion, 25/50/75 percent
  milestones, completion, pause, sanitized failure/warning, stale telemetry,
  and disconnect.
- Maeve dashboard and filament inventory navigation available through the same
  private console instead of opening only on the desktop.

## Deliberate safety limits

- No pause, resume, cancel, print-start, movement, temperature, fan, light, AMS,
  file-transfer, upload, or G-code command path.
- MQTT remains parked and is not used by the live bridge.
- No printer or Maeve service is directly exposed to the LAN or internet.
- Push payloads contain generic event categories, not job names, printer
  identities, account details, network addresses, or credentials.
- Telemetry does not change inventory. A physical spool or completed print must
  be verified before inventory is adjusted.
- Camera analysis cannot label a first layer "good" or diagnose warping yet.

## Prepared next stage

The disabled visual-inspection contract supports conservative results for first
layer, warp, spaghetti, separation, or unknown. It accepts only private local
camera sources, rejects credential-bearing URLs, and can return `looks_good`,
`possible_problem`, or `unable_to_verify`. It cannot control the printer.

The planned hardware package is documented in `MAEVE_SHOPPING_LIST.md`: two
external cameras, a Raspberry Pi, power and storage, optional USB extensions,
and two collision-safe printed mounts. The software must remain disabled until
the hardware exists and known-good and known-bad examples have been labeled.

## Completion score

Two percentages are maintained because "Maeve monitoring" and the full long-term
Maeve vision are different deliverables:

- Monitoring release: **85 percent**. Live telemetry, camera, phone access,
  Rainmeter, AMS visibility, and foreground/background alert plumbing work. The
  remaining monitoring work is full-print event validation, restart recovery,
  notification preference controls, and longer-term reliability evidence.
- Full planned Maeve roadmap: **46 percent**. The future scope also includes
  validated multi-camera inspection and gradually authorized, confirmation-gated
  printer controls. Those capabilities are intentionally not implemented yet.

The full-roadmap score uses this evidence-weighted model:

| Capability | Weight | Earned | Evidence |
|---|---:|---:|---|
| Security and local foundation | 10 | 10 | Loopback-only console, private tailnet access, sanitized state |
| Live telemetry and AMS | 20 | 18 | Working print/AMS feed; active slot is not always reported |
| Phone console and camera | 10 | 10 | Home Screen app, responsive live card, on-demand camera |
| Alerts and notifications | 15 | 12 | Foreground/background delivery and event rules implemented; full-print validation remains |
| Visual inspection | 15 | 3 | Safe disabled contract and tests only; no trained or validated model |
| Guarded printer control | 25 | 0 | Intentionally absent; `control_capable` is false |
| Recovery, operations, and documentation | 5 | 3 | Launchers, rollback notes, tests, and this checkpoint; extended restart evidence remains |
| **Total** | **100** | **46** | |

## Rollback

1. Stop Maeve Command Console using its launcher.
2. Stop the Farm Manager bridge without removing Bambu Farm Manager.
3. Disable Tailscale Serve for Maeve if private phone access must be removed.
4. Leave Rainmeter Print Watch honestly OFFLINE until a verified live source is
   restored.
5. Do not delete protected runtime data, push subscriptions, or printer settings
   during ordinary rollback; preserve them for diagnosis.

This checkpoint intentionally contains no account identity, private URL, network
address, printer serial, access code, push endpoint, token, or other credential.
