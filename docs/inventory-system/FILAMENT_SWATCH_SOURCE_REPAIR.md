# Filament Swatch Source Repair — Deployment Preview

Date: 2026-07-29  
Branch: `feature/filament-manager-v1`  
Starting commit: `1580d3b0961bce7449328ff4b7f0205a86bd2c4a`  
Checkpoint: source only; deployment is not authorized

## Outcome

The dashboard swatch failure is repaired in source without changing production
data or schema. AMS identity and displayed color text continue to come from the
authoritative current assignment and catalog product. The dashboard now carries
the product's optional verified `color_code` into a deterministic swatch
resolver.

Resolution order is:

1. A verified six-digit hexadecimal `color_code`, normalized to lowercase.
2. A normalized canonical color name.
3. An explicit name alias.
4. A two-part slash compound when both parts are recognized.
5. Unknown gray `#777d86` only when no intentional rule resolves the color.

Invalid or non-hex `color_code` text is not trusted as CSS and falls through to
the name rules.

## Exact source-change preview

### `inventory/queries.py`

- Adds the catalog `color_code` attribute to each dashboard AMS-slot projection.
- Does not change assignment selection, spool identity, product identity, or
  remaining quantity.

### `inventory/web.py`

- Passes projected `color_code` to the dashboard swatch resolver.
- Gives a valid `color_code` priority over all name rules.
- Adds canonical Purple as `#800080`.
- Resolves Hot Pink through the Pink family (`#ef8cab`).
- Resolves Cocoa Brown through the Brown family (`#79533a`).
- Resolves recognized two-color slash names as a two-color CSS gradient.
  `Black/Purple` resolves to black plus canonical purple instead of unknown
  gray.
- Retains `#777d86` as the final fallback for genuinely unknown colors.

### `tests/test_web.py`

- Preserves and turns green the three approved Purple, Hot Pink, and Cocoa
  Brown regression tests.
- Adds verified-code priority and invalid-code fallback coverage.
- Adds intentional compound-name coverage for `Black/Purple`.
- Adds explicit genuinely-unknown fallback coverage.
- Adds an end-to-end dashboard case using a temporary migrated database and the
  normal inventory action service. It proves AMS slot identity, displayed
  `Hot Pink` text, and verified `#ff1493` swatch render together after loading
  the temporary spool.

## Test report

All tests used disposable temporary databases.

| Validation | Result |
|---|---:|
| Focused dashboard suite | 35 passed |
| Related replacement, return, and AMS workflow suites | 68 passed |
| Full regression suite | 328 passed |
| Source diff whitespace/error check | Passed |

The end-to-end fixture changes only its disposable database. No repository
database or external runtime database is used by the test.

## Production boundary verification

Production database:
`C:\Users\Cowboy\Documents\THS-Command-Center-Data\inventory.sqlite3`

- Schema: 19 (`019_flexible_spool_replacement.sql`)
- SQLite quick check: `ok`
- Foreign-key violations: 0
- SHA-256 before and after source validation:
  `2C5B3EF08BA222793B494E4B601C44FA88AA34C7CBA24331050C0BB70F90671C`

No production inventory records, assignments, weights, transactions, audit
history, equipment records, telemetry records, or schema objects were changed.
Main was not touched.

## Deployment impact and safety plan

Deploying this commit later changes only read-only dashboard projection and
rendering behavior. It does not require a migration or data correction.

Recommended deployment validation:

1. Reverify the approved source commit and a clean synchronized feature branch.
2. Capture the production database checksum and verify schema 19, integrity,
   and foreign keys read-only.
3. Deploy source only; do not run migrations.
4. Verify dashboard HTTP 200 and confirm Purple, Hot Pink, Cocoa Brown, and
   Black/Purple swatches with their unchanged THS-FIL identities and slot text.
5. Run focused dashboard safety tests against temporary data.
6. Reconfirm the production database checksum is byte-for-byte unchanged.

Stop for explicit deployment authorization.
