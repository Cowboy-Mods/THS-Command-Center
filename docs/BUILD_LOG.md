# THS Command Center Build Log

## 2026-07-26 — Stage 2 Maintenance Registry production checkpoint

### Maintenance Registry completed

- Added permanent maintenance IDs, equipment readiness, backlog views, linked print
  records, SHA-256 photo/video evidence, replay protection, and immutable lifecycle
  history.
- Added controlled workflows for recording faults, creating tasks, waiting for parts,
  completing work, verifying repairs, and reopening failed repairs.
- Added explicit Pending and In progress initial states to Record Fault Discovered.
- Applied migration `012_maintenance_registry.sql` to the live runtime database after a
  verified timestamped backup. Existing inventory, AMS, transaction, audit, print, and
  open-spool registration content remained unchanged.

### First signed production maintenance record

- Committed `THS-MNT-000001` for the Bambu Lab P1S purge-chute sweeper failure.
- Linked the fault to `THS-PRT-000001`, the Tweety orange-hat print accepted with defect.
- Recorded the corrected diagnosis: the sliding purge-chute sweeper detached; the nozzle
  wiper was initially suspected but was not the failed part.
- Recorded the temporary sweeper reattachment, ordered replacement purge chute, spare
  nozzle wiper, and No unattended printing readiness.
- Registered the original Bambu Lab order screenshot as immutable evidence ID `1` using
  SHA-256, without transcribing its shipping address or phone number into maintenance
  notes.
- Verified database integrity and confirmed maintenance history and evidence cannot be
  silently updated or deleted.

### Dashboard and launcher hardening

- Added canonical AMS swatches for Red (`#d32f2f`) and Jade White (`#f4f4f0`) while
  preserving Black (`#24262a`) and Orange (`#ff7a18`).
- Found an untracked older THS process occupying port 8787 and causing current launcher
  checks to accept stale pages.
- Added an isolated checkout-relative Python bootstrap, exact application-path
  verification, startup path diagnostics, occupied-port rejection, and listener-PID
  verification.
- Verified the permanent launcher serves the current dashboard, maintenance workflow,
  and AMS routes from the permanent Git checkout.

### Verified checkpoint

- Source branch: `feature/filament-manager-v1`
- Maintenance Registry implementation: `36e4e87`
- Maintenance/launcher/swatch hardening: `a6a3f15`
- Full suite: 199 tests passing
- Live runtime data, backups, process records, screenshots, and immutable evidence remain
  outside Git.

## 2026-07-12 — Maeve Briefing System v1.0

### Project context
This work belongs under the THS Command Center / room monitor project. The goal is a personal, modular assistant that can be customized by different users rather than acting as a generic Siri or Alexa replacement.

### Completed this weekend

#### Maeve Morning Briefing v1.0
- Built and tested a working morning briefing in Apple Shortcuts.
- Added Maeve system-status opening lines for Maeve Core Systems and the THS Command Center.
- Added current date and time with corrected spoken formatting.
- Added iPhone battery reporting.
- Added current weather reporting, including temperature, conditions, visibility, high, low, precipitation chance, wind speed, wind direction, sunrise, and sunset.
- Improved pacing by splitting weather into separate Text and Speak sections.
- Built a calendar-event repeat loop that counts events and reads each event title and start time.
- Added formatted day, date, and time so events are not mistaken for being on the wrong day.
- Confirmed the morning schedule list works with multiple events.

#### Maeve Evening Briefing v1.0
- Duplicated the morning briefing and converted it into a bedtime / next-day planning briefing.
- Added evening-specific opening language and CPAP reminder.
- Added iPhone battery reporting.
- Added current evening weather plus tomorrow's forecast.
- Fixed Apple Weather's multi-day list behavior by selecting one forecast item from the Daily Forecast list, then pointing Sunrise, High, and Precipitation Chance variables to that single item.
- Added a multi-day upcoming calendar outlook.
- Removed the Meetings-only calendar restriction so Work, Family, Meetings, and other calendars can be included.
- Corrected the event-count condition to use `If Count is 0`.
- Added day, date, time, and title to each listed upcoming event.
- Confirmed the evening briefing can read several upcoming events across multiple days.

### Automation work
- Began configuring an iPhone Personal Automation for the morning briefing.
- Planned morning trigger: run Maeve Morning Briefing v1.0 when an alarm is stopped.
- Planned evening trigger: run Maeve Evening Briefing v1.0 when the iPhone is connected to power at bedtime.

### Key technical lessons
- Apple Weather's Daily Forecast action returns a list of forecast days, not a single day.
- `Get Item from List` must be used before reading tomorrow's Sunrise, High, Low, or Precipitation Chance.
- Weather variables must point to the single selected forecast item, not the original forecast list.
- Calendar event lists can be assembled by repeating through Calendar Events, formatting each Start Date, and appending Text to a report variable.
- A Count result of zero still has a value, so `If Count has any value` is the wrong condition for empty-event handling.

### Current stable versions
- Maeve Morning Briefing v1.0
- Maeve Evening Briefing v1.0

### Next planned work
- Finish and test both iPhone automations.
- Clean up wording, pauses, and voice flow without changing working logic.
- Rename old Meeting variables to Schedule variables.
- Make calendar date ranges fully dynamic.
- Add Bills calendar support, including all-day bill events.
- Add Reminders support.
- Add Apple Watch battery reporting if available through Shortcuts.
- Add low-battery charging reminders.
- Continue integrating Maeve with the THS Command Center, Home Assistant, room monitor, and Get Home workflow.

## 2026-07-26 — Purchase Registry Foundation Phase 1

- Preserved the legacy `orders` and receiving workflow without converting
  `THS-ORD-000001`.
- Added additive migration `013_purchase_registry_foundation.sql` for vendors,
  extensible categories, permanent `THS-PO-######` purchases, immutable lines, and
  immutable signed history.
- Added integer-cent monetary validation, signed expiring zero-write previews,
  explicit confirmation, atomic commits, stale-state checks, and nonce replay
  protection.
- Added read-only purchase verification queries and a purchase-specific migration
  dry run that fingerprints protected operational tables.
- Kept evidence, receiving, inventory integration, maintenance linkage, dashboards,
  analytics, cost accounting, and reorder logic out of Phase 1.

## 2026-07-26 — Dashboard Shop-Health Correction

- Separated operational shop-health evaluation from its visual presentation.
- Equipment readiness now prevents a false all-clear whenever a non-normal
  operational restriction exists.
- Added Shop Ready, Attention Required, and Operation Restricted traffic-signal
  presentation with linked maintenance details.
- Added the Personal by Design, One Engine. Your Workshop., and honest operational
  restriction principles to the tracked Maeve design philosophy.

## 2026-07-26 — Purchase Registry Phase 2A

- Added signed, expiring, zero-write previews for immutable purchase evidence and
  controlled maintenance linkage.
- Kept purchase evidence, delivery evidence, inventory receipt, maintenance
  relevance, and actual installation or consumption as separate facts.
- Added SHA-256 and file-size revalidation, explicit confirmation, replay
  protection, immutable history, and atomic rollback.
- Added migration 014 dry-run protection for all legacy and Phase 1 purchase data.
- Did not create the Bambu purchase, process the Overture receipt, or migrate
  production.

## 2026-07-26 — Cyan/Cayenne AMS swatch correction

- Added the canonical Bambu PLA Basic Cyan swatch (`#0086d6`) and accepted
  `Cayenne` as the shop-facing alias for the same registered color.
- Normalized swatch lookup case and surrounding/repeated whitespace while
  preserving the unknown-color fallback.
- Made no inventory or production database changes.

## 2026-07-26 — Phase 2A signed UUID hardening

- Moved proposed purchase-evidence and maintenance-link UUID generation into
  the signed preview payload.
- Commits now use the exact reviewed UUIDs, preventing identity changes between
  preview and confirmation.

## 2026-07-26 — Legacy order delivery evidence source checkpoint

- Added migration 015 with immutable delivery evidence and history for legacy
  `THS-ORD-*` records.
- Added signed, expiring, zero-write previews with previewed UUIDs, immediate
  commit-time SHA-256 revalidation, replay protection, and atomic history.
- Added privacy screening and a read-only delivery-evidence section on legacy
  order details.
- Kept delivery proof separate from receipt, inventory, installation, and
  consumption. No production evidence or receiving data was written.

## 2026-07-26 — Legacy order receiving hardening

- Added additive migration `016_legacy_order_receiving_hardening.sql` with
  separate physical receipt facts and system-recorded commit time.
- Added signed, expiring, audited in-place catalog correction with immutable
  history and a refill-coil form attribute.
- Added immutable same-order batch/evidence links with commit-time external-file
  SHA-256 and size revalidation.
- Enforced exact full-outstanding receiving; partial receipt remains a separate
  future workflow.
- Bound the batch UUID, THS-FIL IDs, evidence snapshots, and link UUIDs into the
  zero-write signed preview and atomic commit.
- Made no production database, catalog, order, evidence, or inventory changes.

## 2026-07-26 — Catalog identity correction integrity hardening

- Bound exact dependent-order records and supporting legacy delivery evidence
  into signed catalog-correction previews.
- Added preview-time and commit-time external evidence SHA-256 and size
  revalidation.
- Restricted the controlled filament-form value to canonical `Refill coil`
  with safe whitespace and case normalization.
- Added explicit normalized catalog-identity conflict checks during preview and
  commit.
- Preserved preview-bound history UUID, atomic rollback, stale-state, tamper,
  expiration, and replay protections without requiring another migration.
- Made no production catalog, order, evidence, receiving, or inventory changes
  during source development.
