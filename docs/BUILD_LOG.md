# THS Command Center Build Log

## 2026-07-28 — Flexible spool replacement guided UI

- Expanded the guided replacement form to support outgoing Empty, storage
  return, or AMS movement and incoming Sealed, Open, or None outcomes.
- Added explicit storage and AMS source/destination controls, a service-generated
  zero-write final review, signed version-2 plans, stale-state revalidation, and
  friendly zero-write failure pages.
- Preserved version-1 sealed-replacement review and completion compatibility.
- Added a schema-18 safety gate so the flexible form is unavailable until
  Migration 019 receives a separate production deployment.
- Added 12 focused UI tests; wider UI/filament coverage passes 183 tests and the
  full regression suite passes 318 tests.
- Made no production schema/data, purple-color, AMS-onboarding, or main-branch
  changes.

## 2026-07-28 — Flexible spool replacement service layer

- Added the schema-19 `flexibly_replace_active_filament_spool` service contract
  for empty, storage-return, AMS-move, sealed/open incoming, and no-replacement
  operations.
- Validates the complete final AMS layout before writing and permits occupied
  destinations only when the same atomic transaction vacates them.
- Links outgoing and incoming child actions to one immutable explicit-disposition
  parent workflow and rolls back every state, assignment, transaction, and audit
  record on failure.
- Preserved the original sealed-only service method and legacy schema-6 column
  behavior without backfilling or reinterpreting history.
- Added 11 focused service tests; wider filament/service coverage passes 144
  tests and the full regression suite passes 306 tests.
- Made no UI, production database, spool-correction, migration, or main-branch
  changes.

## 2026-07-28 — Flexible spool replacement schema foundation

- Added schema-only Migration 019 for explicit outgoing and incoming spool
  dispositions without fake replacement identities.
- Preserved legacy sealed-replacement columns and existing immutable workflow
  history while making the legacy replacement and destination fields nullable.
- Added constrained storage, AMS-slot, sealed, open, and no-replacement shapes.
- Verified the migration against a disposable production copy: schema 18 to 19,
  75 protected table fingerprints unchanged, integrity OK, and zero foreign-key
  violations.
- Added eight migration/schema tests; focused filament suites pass 133 tests and
  the complete regression suite passes 295 tests.
- Kept production at schema 18 and made no spool, equipment, telemetry, UI, or
  service-layer changes.

## 2026-07-27 — First Equipment Registry onboarding

- Registered Cowboy's Bambu Lab P1S as `THS-EQP-000001` through the signed,
  zero-write-preview Equipment Registry workflow.
- Recorded one installed/operating 3D-printer record with verified ownership,
  purchase date, THS print-room location, Wi-Fi support, AMS support, and notes.
- Kept unknown serial, THS asset identifier, and exact installation/
  commissioning timestamps null.
- Recorded the built-in camera only as a supported embedded capability/component.
- Created one immutable equipment-history row and one general audit event.
- Created no AMS, camera equipment, telemetry, relationship, interface,
  connection, purchase, receipt, inventory, or assignment records.

## 2026-07-27 — Equipment Registry v1 source foundation

- Added additive Migration 018 with permanent `THS-EQP` identity, controlled
  types/subtypes, stable equipment facts, embedded capabilities, normalized
  interfaces/connections, provenance bridges, and immutable histories.
- Preserved the legacy AMS `equipment` and `equipment_slots` structures.
- Added signed, expiring, zero-write registration and relationship previews with
  preview-bound identities, stale/tamper/replay/duplicate/sequence protection,
  atomic commits, and audit events.
- Kept operational status, maintenance readiness, derived restrictions, stable
  capabilities, and freshness-aware telemetry as separate concepts.
- Added future Bambu, camera-viewing, and print-correlation protocol seams
  without device communication or stream handling.
- Added read-only equipment list/detail/relationship/connection projections and
  focused temporary-database tests.
- Created no equipment or telemetry rows and did not apply Migration 018 to
  production.

## 2026-07-27 — Purchase Registry Receiving source checkpoint

- Added additive migration 017 for controlled fulfillment state, immutable
  receipts, line-specific receiving, evidence links, inventory links, and
  derived outstanding quantities.
- Added signed, expiring, zero-write status and receipt previews with permanent
  identities, evidence revalidation, stale-state checks, replay protection,
  sequence protection, and atomic rollback.
- Added separate individual, quantity, lot, and non-inventory receiving
  behavior through the Inventory Action Service.
- Recorded the design rule that receiving means verified physical arrival only
  and never implies installation, opening, assignment, loading, usage, or
  consumption.
- Kept `THS-PO-000001` and production inventory untouched during source
  development.

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

## 2026-07-26 — Completed Overture receiving lifecycle

- Completed Purchase Registry Phase 1, immutable purchase evidence, and
  maintenance linkage while keeping purchase, delivery, receipt, installation,
  and consumption as separate facts.
- Registered immutable legacy delivery evidence, corrected catalog item 18 in
  place to Overture High Speed PLA White refill coil, and preserved its signed
  order and evidence dependencies.
- Received `THS-ORD-000001` as one evidence-backed atomic batch with date-only
  receipt semantics and strict full-outstanding quantity enforcement.
- Created sealed refill records `THS-FIL-000034` through `THS-FIL-000037` at
  Sealed Filament Rack without AMS, RFID, reusable-spool, or consumption state.
- Preserved preview-bound batch, filament, evidence-link, nonce, and immutable
  audit identities through commit.
- Production remains intentionally unchanged for `THS-PO-000001` (Ordered) and
  `THS-MNT-000001` (In progress, No unattended printing).
# 2026-07-28 — THS-FIL-000032 / THS-FIL-000039 zero-write correction preview

- Added a reusable read-only correction-preview generator for the flexible
  schema-19 service workflow.
- Inspected production schema 18 with immutable/query-only SQLite access.
- Documented the two spool records, AMS assignments, relevant immutable
  history, exact proposed row changes, confirmation questions, preconditions,
  rollback, and post-correction verification.
- Focused correction/service/UI tests passed: 26.
- Full regression suite passed: 321.
- Production SHA-256 remained
  `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`;
  schema remained 18, integrity was `ok`, and foreign-key violations were zero.
- Production Migration 019 and the spool correction were not applied.
# 2026-07-28 — Migration 019 production deployment readiness

- Captured Cowboy's physical confirmations for the later 032/039 correction.
- Reverified production read-only at schema 18 with integrity `ok`, zero
  foreign-key violations, and SHA-256
  `3BF3F098CC1D779E81489BED64B4D654C5836E1E2B75A248CDEA5676B8FFC99A`.
- Created and verified a byte-matched external rollback backup.
- Rehearsed only Migration 019 on a verified production copy: candidate reached
  schema 19; all 75 protected table fingerprints and both target spools remained
  unchanged.
- Rehearsed restoration from the external backup and recovered the exact
  schema-18 baseline hash.
- Documented the exact deployment, validation, stale-state stop, and rollback
  procedures. Production deployment and the spool correction remain blocked
  pending separate explicit authorization.
- Focused Migration 019/service/UI/correction-preview tests passed: 34.
- Full regression suite passed: 321.
# 2026-07-28 — Migration 019 production deployment and validation

- Reverified the exact readiness SHA-256, schema 18, clean integrity/foreign
  keys, repository state, sole pending migration, and byte-matched external
  rollback backup before opening production for write.
- Applied only `019_flexible_spool_replacement.sql`; production advanced
  exactly 18 to 19.
- Production after SHA-256:
  `5820C87D6812EB0699686CB958DBA1B2464C8E022A88F93E257179FEC51B0C52`.
- All 75 protected content fingerprints, both target spools, equipment,
  telemetry, and workflow row counts remained unchanged.
- Post-deployment integrity and quick checks were `ok`; foreign-key violations
  remained zero.
- Focused Migration 019/service/UI/preview tests passed: 34.
- Full regression suite passed: 321.
- Dashboard and guided replacement routes returned HTTP 200 with schema-19
  controls enabled and zero database writes.
- The physically approved 032/039 correction remains unapplied pending its
  separate audited correction checkpoint.
