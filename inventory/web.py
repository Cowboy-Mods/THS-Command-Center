from __future__ import annotations

import html
import mimetypes
import re
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .db import DEFAULT_DB, ROOT, connect
from .navigation import MODULES, NAVIGATION
from .queries import DatabaseNotReady, InventoryQueries
from .receiving import ReceiveSpoolError, ReceiveSpoolWorkflow
from .replacement import (
    ReplaceActiveFilamentSpoolWorkflow,
    ReplaceSpoolError,
)
from .initialization import (
    InitializeAMSError,
    InitializeVerifiedAMSStateWorkflow,
)
from .orders import OrderReceiptError, OrderReceiptWorkflow
from .returning import ReturnSpoolError, ReturnSpoolToStorageWorkflow
from .actions import ActionContext
from .production import ProductionError, ProductionService
from .open_spool import RegisterExistingOpenSpoolWorkflow, RegisterOpenSpoolError
from .maintenance import MaintenanceError, MaintenanceWorkflow

STATIC = ROOT / "inventory" / "static"


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def grams(value) -> str:
    return f"{float(value or 0):,.0f} g"


def kilograms(value) -> str:
    return f"{float(value or 0) / 1000:,.1f} kg"


def display(value, fallback="Not recorded") -> str:
    return esc(value) if value not in (None, "") else f'<span class="muted">{esc(fallback)}</span>'


class InventoryWebApp:
    def __init__(self, database=DEFAULT_DB):
        self.database = Path(database)
        self.queries = InventoryQueries(self.database)
        self.receiving = ReceiveSpoolWorkflow(self.database)
        self.replacement = ReplaceActiveFilamentSpoolWorkflow(self.database)
        self.initialization = InitializeVerifiedAMSStateWorkflow(self.database)
        self.order_receiving = OrderReceiptWorkflow(self.database)
        self.returning = ReturnSpoolToStorageWorkflow(self.database)
        self.open_spool = RegisterExistingOpenSpoolWorkflow(self.database)
        self.maintenance = MaintenanceWorkflow(self.database)

    def response(
        self, target: str, *, method: str = "GET", form: dict[str, str] | None = None,
    ) -> tuple[int, list[tuple[str, str]], bytes]:
        url = urlsplit(target)
        if url.path.startswith("/static/"):
            return self._static(url.path)
        try:
            body, status = self._route(
                method.upper(), url.path, parse_qs(url.query), form or {}
            )
        except DatabaseNotReady as exc:
            body, status = self._database_error(str(exc)), 503
        except ReceiveSpoolError as exc:
            body, status = self._receive_error(str(exc)), 422
        except ReplaceSpoolError as exc:
            body, status = self._replacement_error(str(exc)), 422
        except InitializeAMSError as exc:
            body, status = self._initialization_error(str(exc)), 422
        except OrderReceiptError as exc:
            body, status = self._order_receipt_error(str(exc)), 422
        except ReturnSpoolError as exc:
            body, status = self._return_spool_error(str(exc)), 422
        except ProductionError as exc:
            body, status = self._production_error(str(exc)), 422
        except RegisterOpenSpoolError as exc:
            body, status = self._open_spool_error(str(exc)), 422
        except MaintenanceError as exc:
            body, status = self._maintenance_error(str(exc)), 422
        except Exception:
            body, status = self._error_page(
                "Something went wrong",
                "The inventory page could not be loaded. Check the application terminal for details.",
            ), 500
        content = body.encode("utf-8")
        return status, [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(content))),
            ("Cache-Control", "no-store"),
        ], content

    def _route(
        self, method: str, path: str, query: dict[str, list[str]], form: dict[str, str],
    ) -> tuple[str, int]:
        if method == "GET" and path == "/inventory/filament/receive":
            return self._receive_form(), 200
        if method == "POST" and path == "/inventory/filament/receive/review":
            return self._receive_review(self.receiving.review(form)), 200
        if method == "POST" and path == "/inventory/filament/receive/confirm":
            if form.get("confirm") != "receive":
                raise ReceiveSpoolError("explicit confirmation is required")
            return self._receive_complete(self.receiving.commit(form.get("review_token", ""))), 201
        if method == "GET" and path == "/inventory/filament/replace":
            filters = {key: values[0] for key, values in query.items() if values}
            return self._replacement_form(filters), 200
        if method == "POST" and path == "/inventory/filament/replace/review":
            return self._replacement_review(self.replacement.review(form)), 200
        if method == "POST" and path == "/inventory/filament/replace/confirm":
            if form.get("confirm") != "replace":
                raise ReplaceSpoolError("explicit replacement confirmation is required")
            return self._replacement_complete(
                self.replacement.commit(form.get("review_token", ""))
            ), 201
        if method == "GET" and path == "/inventory/filament/ams/initialize":
            return self._initialization_form(), 200
        if method == "POST" and path == "/inventory/filament/ams/initialize/review":
            return self._initialization_review(self.initialization.review(form)), 200
        if method == "POST" and path == "/inventory/filament/ams/initialize/confirm":
            if form.get("confirm") != "initialize":
                raise InitializeAMSError("explicit initialization confirmation is required")
            return self._initialization_complete(
                self.initialization.commit(form.get("review_token", ""))
            ), 201
        if method == "GET" and path == "/inventory/filament/ams/return":
            return self._return_spool_form(), 200
        if method == "POST" and path == "/inventory/filament/ams/return/review":
            return self._return_spool_review(self.returning.review(form)), 200
        if method == "POST" and path == "/inventory/filament/ams/return/confirm":
            if form.get("confirm") != "return-spool":
                raise ReturnSpoolError("explicit return confirmation is required")
            return self._return_spool_complete(
                self.returning.commit(form.get("review_token", ""))
            ), 201
        if method == "POST" and path == "/orders/receive/review":
            return self._order_receipt_review(self.order_receiving.review(form)), 200
        if method == "POST" and path == "/orders/receive/confirm":
            if form.get("confirm") != "receive-order":
                raise OrderReceiptError("explicit order receipt confirmation is required")
            return self._order_receipt_complete(
                self.order_receiving.commit(form.get("review_token", ""))
            ), 201
        if method == "GET" and path == "/inventory/filament/register-open":
            return self._open_spool_form(), 200
        if method == "POST" and path == "/inventory/filament/register-open/review":
            return self._open_spool_review(self.open_spool.review(form)), 200
        if method == "POST" and path == "/inventory/filament/register-open/confirm":
            if form.get("confirm") != "register-open-spool":
                raise RegisterOpenSpoolError("explicit registration confirmation is required")
            return self._open_spool_complete(
                self.open_spool.commit(form.get("review_token", ""))
            ), 201
        if method == "POST" and path == "/prints/complete":
            if form.get("confirm") != "complete-print":
                raise ProductionError("explicit print completion confirmation is required")
            return self._print_complete(form), 201
        if method == "POST" and path == "/maintenance/review":
            return self._maintenance_review(
                self.maintenance.review(form.get("action", ""), form)
            ), 200
        if method == "POST" and path == "/maintenance/confirm":
            if form.get("confirm") != "maintenance-write":
                raise MaintenanceError("explicit maintenance confirmation is required")
            return self._maintenance_complete(
                self.maintenance.commit(form.get("review_token", ""))
            ), 201
        if method == "POST" and path == "/maintenance/evidence":
            if form.get("confirm") != "maintenance-evidence":
                raise MaintenanceError("explicit evidence confirmation is required")
            return self._maintenance_evidence_complete(form), 201
        if method != "GET":
            return self._method_not_allowed(), 405
        if path == "/":
            return self._operational_dashboard(), 200
        if path == "/inventory/filament":
            return self._filament_inventory(query), 200
        if path == "/inventory/filament/ams":
            return self._ams(), 200
        if path == "/orders":
            return self._orders(), 200
        if path == "/prints":
            return self._prints(), 200
        if path == "/prints/complete":
            return self._print_completion_form(), 200
        if path == "/maintenance":
            return self._maintenance(), 200
        if path == "/maintenance/action":
            values = {key: rows[0] for key, rows in query.items() if rows}
            return self._maintenance_form(values), 200
        if path == "/maintenance/evidence":
            values = {key: rows[0] for key, rows in query.items() if rows}
            return self._maintenance_evidence_form(values), 200
        if path == "/audit":
            return self._audit_mode(), 200
        if path == "/projects":
            return self._projects(), 200
        match = re.fullmatch(r"/orders/(\d+)/receive", path)
        if match:
            return self._order_receipt_form(int(match.group(1))), 200
        match = re.fullmatch(r"/inventory/filament/products/(\d+)", path)
        if match:
            product = self.queries.product_detail(int(match.group(1)))
            return (self._product(product), 200) if product else (self._not_found(), 404)
        match = re.fullmatch(r"/inventory/filament/spools/(\d+)", path)
        if match:
            spool = self.queries.spool_detail(int(match.group(1)))
            return (self._spool(spool), 200) if spool else (self._not_found(), 404)
        match = re.fullmatch(r"/modules/([a-z0-9-]+)", path)
        if match and match.group(1) in MODULES:
            return self._placeholder(MODULES[match.group(1)]), 200
        return self._not_found(), 404

    def _open_spool_form(self) -> str:
        options = self.open_spool.options()
        products = "".join(
            f'<option value="{p["id"]}">{esc(p["manufacturer"])} · '
            f'{esc(p["product_line"])} · {esc(p["color"])} ({esc(p["material"])})</option>'
            for p in options["products"]
        )
        locations = "".join(
            f'<option value="storage:{r["id"]}">Storage · {esc(r["name"])}</option>'
            for r in options["locations"]
        ) + "".join(
            f'<option value="ams:{r["id"]}">{esc(r["equipment_name"])} · '
            f'Slot {r["slot_number"]}</option>' for r in options["slots"]
        )
        return self._shell(
            "Register Existing Open Spool",
            f"""<div class="notice"><strong>Legacy inventory only</strong>
            <p>Use this for one physical spool that was opened before THS tracking began.
            Do not use it for a new sealed spool.</p></div>
            <form class="receive-form" method="post"
              action="/inventory/filament/register-open/review">
            <fieldset><legend>1. Manufacturer, material, and color</legend>
              <label class="choice"><input type="radio" name="product_mode"
                value="existing" checked><span><strong>Select existing catalog product</strong></span></label>
              <label><span>Existing product</span><select name="catalog_item_id">
                <option value="">Select a product</option>{products}</select></label>
              <label class="choice"><input type="radio" name="product_mode" value="new">
                <span><strong>Create missing catalog identity</strong>
                <small>No nominal or 1,000 g weight is required.</small></span></label>
              <div class="form-grid">
                <label><span>Manufacturer</span><input name="manufacturer" maxlength="120"></label>
                <label><span>Material / type</span><input name="material" maxlength="120"></label>
                <label><span>Color</span><input name="color" maxlength="120"></label>
              </div>
            </fieldset>
            <fieldset><legend>2. Remaining quantity</legend><div class="form-grid">
              <label><span>Quantity mode</span><select name="quantity_mode" required>
                <option value="exact">Exact grams</option>
                <option value="estimated">Estimated grams</option>
                <option value="unknown">Unknown</option></select></label>
              <label><span>Remaining grams</span><input name="remaining_quantity"
                type="number" min="0" step="0.01" inputmode="decimal"
                placeholder="Leave blank only when unknown"></label>
              <label><span>Confidence / source</span><select name="quantity_confidence" required>
                <option value="weighed">Weighed</option>
                <option value="manufacturer_estimate">Manufacturer estimate</option>
                <option value="visual_estimate">Visual estimate</option>
                <option value="unknown">Unknown</option></select></label>
              <label class="wide-field"><span>Quantity note</span>
                <textarea name="note" maxlength="1000" rows="3"
                placeholder="Required for estimated or unknown quantity"></textarea></label>
            </div></fieldset>
            <fieldset><legend>3. Physical location and duplicate check</legend>
              <label><span>Current location</span><select name="initial_location" required>
                <option value="">Select storage or an empty AMS slot</option>{locations}</select></label>
              <label><span>Actor</span><input name="actor" value="Cowboy" required></label>
              <label class="confirmation"><input type="checkbox"
                name="physical_spool_confirmed" value="yes" required><span>I physically
                verified this is one open spool and it is not already registered.</span></label>
              <div class="notice warning"><strong>Duplicate warning</strong><p>Same-brand,
                same-material, same-color spools are allowed. Check the box only after
                confirming this is a different physical spool from any warning shown.</p></div>
              <label class="confirmation"><input type="checkbox"
                name="duplicate_warning_ack" value="yes"><span>I reviewed possible matching
                open or AMS-loaded spools and this is a different physical spool.</span></label>
            </fieldset>
            <div class="notice subdued"><strong>Fixed by this workflow</strong>
              <p>Condition: Open · Source: Pre-existing inventory · One permanent THS-FIL ID</p></div>
            <div class="form-actions"><a href="/inventory/filament">Cancel</a>
              <button type="submit">Preview registration</button></div></form>""",
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / Register open spool',
            description="Preview first. Nothing is written until final confirmation.",
        )

    def _open_spool_review(self, review) -> str:
        v = review.values
        quantity = (
            "Unknown" if v["remaining_quantity"] is None
            else f'{v["remaining_quantity"]:g} g'
        )
        destination = (
            v["destination"]["name"] if v["location_type"] == "storage"
            else f'{v["destination"]["equipment_name"]} Slot {v["destination"]["slot_number"]}'
        )
        warning = (
            f'<div class="notice warning"><strong>Duplicate warning acknowledged</strong>'
            f'<p>{v["duplicate_warning_count"]} similar open or loaded spool(s) already exist. '
            f'This registration is allowed because the user confirmed a distinct physical spool.</p></div>'
            if v["duplicate_warning_count"] else
            '<div class="notice"><strong>No matching active open spool found</strong></div>'
        )
        return self._shell(
            "Review Open Spool Registration",
            f"""{warning}<section class="panel"><dl>
              <div><dt>Permanent ID</dt><dd>{esc(v["permanent_id"])}</dd></div>
              <div><dt>Manufacturer</dt><dd>{esc(v["product"]["manufacturer"])}</dd></div>
              <div><dt>Material / type</dt><dd>{esc(v["product"]["material"])}</dd></div>
              <div><dt>Color</dt><dd>{esc(v["product"]["color"])}</dd></div>
              <div><dt>Condition</dt><dd>Open</dd></div>
              <div><dt>Source</dt><dd>Pre-existing inventory</dd></div>
              <div><dt>Remaining</dt><dd>{esc(quantity)}</dd></div>
              <div><dt>Quantity mode</dt><dd>{esc(v["quantity_mode"].title())}</dd></div>
              <div><dt>Confidence</dt><dd>{esc(v["quantity_confidence"].replace("_", " ").title())}</dd></div>
              <div><dt>Current location</dt><dd>{esc(destination)}</dd></div>
              <div><dt>Note</dt><dd>{display(v["note"])}</dd></div>
            </dl></section>
            <form class="confirm-form" method="post"
              action="/inventory/filament/register-open/confirm">
              <input type="hidden" name="review_token" value="{esc(review.token)}">
              <label class="confirmation"><input type="checkbox" name="confirm"
                value="register-open-spool" required><span>Create exactly one permanent
                physical spool record with this reviewed information.</span></label>
              <div class="form-actions"><a href="/inventory/filament/register-open">
                Go back without saving</a><button type="submit">Register open spool</button></div>
            </form>""",
            '<a href="/">Dashboard</a> / <a href="/inventory/filament/register-open">Register open spool</a> / Review',
        )

    def _open_spool_complete(self, result: dict) -> str:
        return self._shell(
            "Open Spool Registered",
            f"""<section class="success-panel"><p class="eyebrow">Committed atomically</p>
              <h1>{esc(result["permanent_id"])}</h1>
              <p>One pre-existing physical spool is now permanent inventory history.</p>
              <dl><div><dt>Registration</dt><dd>#{result["registration_id"]}</dd></div>
              <div><dt>Inventory audit</dt><dd>#{result["add_action_id"]}</dd></div>
              <div><dt>AMS load audit</dt><dd>{display(result["load_action_id"], "Registered in storage")}</dd></div></dl>
              <a class="primary-link" href="/inventory/filament/spools/{result["instance_id"]}">
                View spool</a></section>""",
            '<a href="/">Dashboard</a> / <a href="/inventory/filament/register-open">Register open spool</a> / Complete',
        )

    def _open_spool_error(self, message: str) -> str:
        return self._error_page(
            "Open spool registration stopped", message, status="Nothing registered"
        )

    def _production_service(self, actor: str, module="print-registry-ui"):
        return ProductionService(
            self.database, ActionContext(actor=actor, module=module, origin="user")
        )

    def _prints(self) -> str:
        with closing(connect(self.database)) as db:
            rows = db.execute(
                """SELECT pr.*,p.name project_name,r.name printer_name,
                (SELECT COUNT(*) FROM print_evidence e WHERE e.print_record_id=pr.id) evidence_count
                FROM print_records pr LEFT JOIN projects p ON p.id=pr.project_id
                LEFT JOIN printers r ON r.id=pr.printer_id
                ORDER BY pr.completed_at DESC,pr.id DESC"""
            ).fetchall()
        items = "".join(
            f"""<tr><td data-label="Print">{esc(r["print_number"])}</td>
            <td data-label="Part">{esc(r["part_name"])}</td>
            <td data-label="Plate">{display(r["plate_name"])}</td>
            <td data-label="Inspection">{esc(r["inspection_status"].replace("_", " ").title())}</td>
            <td data-label="Evidence">{r["evidence_count"]}</td>
            <td data-label="Completed">{esc(r["completed_at"])}</td></tr>"""
            for r in rows
        ) or '<tr><td colspan="6">No production records yet.</td></tr>'
        return self._shell(
            "Print Registry",
            f"""<section class="page-heading"><div><p class="eyebrow">Production</p>
            <h1>Print Registry</h1><p>Permanent print completion and inspection history.</p></div>
            <a class="primary-link" href="/prints/complete">Record completed print</a></section>
            <section class="panel table-panel"><table><thead><tr><th>Print</th><th>Part</th>
            <th>Plate</th><th>Inspection</th><th>Evidence</th><th>Completed</th></tr></thead>
            <tbody>{items}</tbody></table></section>""",
            '<a href="/">Dashboard</a> / Print Registry',
        )

    def _print_completion_form(self) -> str:
        with closing(connect(self.database)) as db:
            printers = db.execute("SELECT id,name FROM printers ORDER BY name").fetchall()
            projects = db.execute(
                "SELECT id,name FROM projects WHERE archived_at IS NULL ORDER BY name"
            ).fetchall()
        printer_options = '<option value="">Not linked</option>' + "".join(
            f'<option value="{r["id"]}">{esc(r["name"])}</option>' for r in printers
        )
        project_options = '<option value="">Not linked</option>' + "".join(
            f'<option value="{r["id"]}">{esc(r["name"])}</option>' for r in projects
        )
        return self._shell(
            "Complete Print",
            f"""<section class="page-heading"><div><p class="eyebrow">Controlled workflow</p>
            <h1>Record Print Completion</h1><p>Inspect the physical part before committing permanent history.</p></div></section>
            <section class="panel"><form class="receive-form" method="post" action="/prints/complete">
            <label><span>Job name</span><input name="job_name" maxlength="200" required></label>
            <label><span>Plate</span><input name="plate_name" maxlength="200"></label>
            <label><span>Part</span><input name="part_name" maxlength="200" required></label>
            <label><span>Quantity</span><input name="quantity" type="number" min="1" value="1" required></label>
            <label><span>Printer</span><select name="printer_id">{printer_options}</select></label>
            <label><span>Project</span><select name="project_id">{project_options}</select></label>
            <label><span>Completed at (RFC3339)</span>
            <input name="completed_at" placeholder="2026-07-26T09:00:00-04:00" required></label>
            <label><span>Completion time accuracy</span><select name="completion_time_accuracy">
            <option value="exact">Exact</option><option value="estimated">Estimated</option>
            <option value="unknown">Unknown</option></select></label>
            <label><span>Inspection</span><select name="inspection_status" required>
            <option value="accepted">Accepted</option>
            <option value="accepted_with_defect">Accepted with defect</option>
            <option value="rejected">Rejected</option></select></label>
            <label><span>Defect notes</span><textarea name="defect_notes"></textarea></label>
            <label><span>Operator</span><input name="actor" value="Cowboy" maxlength="100" required></label>
            <label><span>Notes</span><textarea name="notes"></textarea></label>
            <label class="confirmation"><input type="checkbox" name="confirm"
            value="complete-print" required><span>I physically inspected this print and approve
            creation of a permanent production record.</span></label>
            <div class="form-actions"><a href="/prints">Cancel</a>
            <button type="submit">Record completed print</button></div></form></section>""",
            '<a href="/">Dashboard</a> / <a href="/prints">Print Registry</a> / Complete',
        )

    def _print_complete(self, form: dict[str, str]) -> str:
        def optional_int(name):
            value = str(form.get(name, "")).strip()
            return int(value) if value else None
        try:
            quantity = int(form.get("quantity", "1"))
        except ValueError as exc:
            raise ProductionError("quantity must be a whole number") from exc
        result = self._production_service(form.get("actor", "")).complete_print(
            job_name=form.get("job_name", ""), plate_name=form.get("plate_name"),
            part_name=form.get("part_name", ""), quantity=quantity,
            printer_id=optional_int("printer_id"), project_id=optional_int("project_id"),
            completed_at=form.get("completed_at", ""),
            completion_time_accuracy=form.get("completion_time_accuracy", "exact"),
            inspection_status=form.get("inspection_status", ""),
            defect_notes=form.get("defect_notes"), notes=form.get("notes"),
            request_nonce=form.get("request_nonce") or None,
        )
        return self._shell(
            "Print Recorded",
            f"""<section class="success-panel"><p class="eyebrow">Committed</p>
            <h1>{esc(result["print_number"])}</h1><p>The completed print and inspection
            are now permanent production history.</p><dl><div><dt>Inspection</dt>
            <dd>{esc(result["inspection_status"].replace("_", " ").title())}</dd></div>
            <div><dt>Audit event</dt><dd>#{result["audit_id"]}</dd></div></dl>
            <a class="primary-link" href="/prints">View Print Registry</a></section>""",
            '<a href="/">Dashboard</a> / <a href="/prints">Print Registry</a> / Recorded',
        )

    def _legacy_maintenance(self) -> str:
        with closing(connect(self.database)) as db:
            rows = db.execute(
                """SELECT me.*,p.name printer_name,pr.print_number
                FROM maintenance_events me LEFT JOIN printers p ON p.id=me.printer_id
                LEFT JOIN print_records pr ON pr.id=me.related_print_id
                ORDER BY me.occurred_at DESC,me.id DESC"""
            ).fetchall()
            printers = db.execute("SELECT id,name FROM printers ORDER BY name").fetchall()
        history = "".join(
            f"<li><strong>{esc(r['event_number'])}: {esc(r['summary'])}</strong>"
            f"<small>{esc(r['occurred_at'])} · {esc(r['severity'].title())}</small></li>"
            for r in rows
        ) or "<li>No maintenance events recorded.</li>"
        options = '<option value="">Not linked</option>' + "".join(
            f'<option value="{r["id"]}">{esc(r["name"])}</option>' for r in printers
        )
        return self._shell(
            "Maintenance",
            f"""<section class="page-heading"><div><p class="eyebrow">Shop history</p>
            <h1>Maintenance Events</h1><p>Permanent equipment incidents and service history.</p></div></section>
            <section class="panel"><form class="receive-form" method="post" action="/maintenance/log">
            <label><span>Event type</span><input name="event_type" value="poop_chute_backup" required></label>
            <label><span>Summary</span><input name="summary" required></label>
            <label><span>Details</span><textarea name="details"></textarea></label>
            <label><span>Severity</span><select name="severity"><option>info</option>
            <option selected>warning</option><option>critical</option></select></label>
            <label><span>Occurred at (RFC3339)</span><input name="occurred_at" required></label>
            <label><span>Printer</span><select name="printer_id">{options}</select></label>
            <label><span>Actor</span><input name="actor" value="Cowboy" required></label>
            <label class="confirmation"><input type="checkbox" name="confirm"
            value="log-maintenance" required><span>I verified this event and approve permanent logging.</span></label>
            <button type="submit">Log maintenance event</button></form></section>
            <section class="panel"><h2>Service history</h2><ul class="activity-list">{history}</ul></section>""",
            '<a href="/">Dashboard</a> / Maintenance',
        )

    def _legacy_maintenance_complete(self, form: dict[str, str]) -> str:
        printer = str(form.get("printer_id", "")).strip()
        result = self._production_service(
            form.get("actor", ""), "maintenance-ui"
        ).log_maintenance(
            event_type=form.get("event_type", ""), summary=form.get("summary", ""),
            details=form.get("details"), severity=form.get("severity", "info"),
            occurred_at=form.get("occurred_at", ""),
            printer_id=int(printer) if printer else None,
        )
        return self._shell(
            "Maintenance Recorded",
            f"""<section class="success-panel"><p class="eyebrow">Committed</p>
            <h1>{esc(result["event_number"])}</h1><p>The maintenance event is permanent history.</p>
            <a class="primary-link" href="/maintenance">View maintenance history</a></section>""",
            '<a href="/">Dashboard</a> / <a href="/maintenance">Maintenance</a> / Recorded',
        )

    def _maintenance(self) -> str:
        backlog = MaintenanceWorkflow.backlog(self.database)

        def cards(rows):
            return "".join(
                f"""<article class="order-card" id="maintenance-{r["id"]}">
                <p class="eyebrow">{esc(r["event_number"])}</p>
                <h2>{esc(r["display_name"])}</h2><p>{esc(r["symptoms"])}</p>
                <p><strong>{esc(r["status"].replace("_", " ").title())}</strong> ·
                {esc(r["severity"].replace("_", " ").title())} ·
                {r["evidence_count"]} evidence file(s)</p>
                <a href="/maintenance/action?action=complete_maintenance&id={r["id"]}">Update task</a>
                </article>""" for r in rows
            ) or "<p>No records in this section.</p>"

        assets = "".join(
            f"""<tr><td>{esc(r["display_name"])}</td>
            <td>{esc(r["asset_type"].replace("_", " ").title())}</td>
            <td>{esc(r["readiness_state"].replace("_", " ").title())}</td></tr>"""
            for r in backlog["assets"]
        )
        return self._shell(
            "Maintenance Backlog",
            f"""<section class="page-heading"><div><p class="eyebrow">Permanent registry</p>
            <h1>Maintenance Backlog</h1><p>Equipment readiness, open work, blocked work,
            overdue tasks, and permanent repair history.</p></div></section>
            <section class="panel"><h2>Controlled workflows</h2><div class="form-actions">
            <a class="primary-link" href="/maintenance/action?action=record_fault">Record Fault Discovered</a>
            <a href="/maintenance/action?action=create_task">Create Maintenance Task</a></div></section>
            <section><h2>Open tasks</h2><div class="order-list">{cards(backlog["open"])}</div></section>
            <section><h2>Blocked tasks</h2><div class="order-list">{cards(backlog["blocked"])}</div></section>
            <section><h2>Overdue tasks</h2><div class="order-list">{cards(backlog["overdue"])}</div></section>
            <section><h2>Completed history</h2><div class="order-list">{cards(backlog["completed"])}</div></section>
            <section class="panel table-panel"><h2>Equipment status</h2><table><thead>
            <tr><th>Equipment</th><th>Type</th><th>Readiness</th></tr></thead>
            <tbody>{assets}</tbody></table></section>""",
            '<a href="/">Dashboard</a> / Maintenance',
        )

    def _maintenance_form(self, query: dict[str, str]) -> str:
        action = query.get("action", "record_fault")
        if action not in MaintenanceWorkflow.ACTION_TARGETS:
            raise MaintenanceError("unsupported maintenance workflow")
        record_id = query.get("id", "")
        options = self.maintenance.options()
        assets = "".join(
            f'<option value="{r["id"]}">{esc(r["display_name"])}</option>'
            for r in options["assets"]
        )
        prints = '<option value="">Not linked</option>' + "".join(
            f'<option value="{r["id"]}">{esc(r["print_number"])} · {esc(r["part_name"])}</option>'
            for r in options["prints"]
        )
        if action in {"record_fault", "create_task"}:
            event_types = "".join(
                f'<option value="{v}"'
                f'{" selected" if action == "record_fault" and v == "fault_discovered" else ""}>'
                f'{v.replace("_", " ").title()}</option>'
                for v in sorted(MaintenanceWorkflow.EVENT_TYPES)
            )
            severities = "".join(
                f'<option value="{v}">{v.replace("_", " ").title()}</option>'
                for v in sorted(MaintenanceWorkflow.SEVERITIES)
            )
            initial_status = (
                """<label><span>Initial status</span><select name="initial_status">
                <option value="pending" selected>Pending</option>
                <option value="in_progress">In progress</option></select></label>"""
                if action == "record_fault" else ""
            )
            fields = f"""<label><span>Equipment / printer</span><select name="asset_id"
            required>{assets}</select></label><label><span>Event type</span>
            <select name="event_type">{event_types}</select></label>
            {initial_status}
            <label><span>Severity</span><select name="severity">{severities}</select></label>
            <label><span>Discovered at (RFC3339)</span><input name="discovered_at" required></label>
            <label><span>Due at (optional RFC3339)</span><input name="due_at"></label>
            <label><span>Symptoms</span><textarea name="symptoms" required></textarea></label>
            <label><span>Likely cause</span><textarea name="likely_cause"></textarea></label>
            <label><span>Corrective action</span><textarea name="corrective_action"></textarea></label>
            <label><span>Parts required</span><textarea name="parts_required"></textarea></label>
            <label><span>Parts used</span><textarea name="parts_used"></textarea></label>
            <label><span>Related print</span><select name="related_print_id">{prints}</select></label>
            <label><span>Notes</span><textarea name="notes"></textarea></label>"""
            workflow_links = ""
        else:
            fields = f"""<input type="hidden" name="record_id" value="{esc(record_id)}">
            <label><span>Reason / work performed</span><textarea name="reason" required></textarea></label>
            <label><span>Parts required</span><textarea name="parts_required"></textarea></label>
            <label><span>Parts used</span><textarea name="parts_used"></textarea></label>
            <label><span>Corrective action</span><textarea name="corrective_action"></textarea></label>
            <label><span>Completed at (required for completion/verification)</span>
            <input name="completed_at"></label>"""
            workflow_links = f"""<div class="form-actions">
            <a href="/maintenance/action?action=mark_waiting_for_part&id={esc(record_id)}">Mark Waiting for Part</a>
            <a href="/maintenance/action?action=complete_maintenance&id={esc(record_id)}">Complete Maintenance</a>
            <a href="/maintenance/action?action=verify_repair&id={esc(record_id)}">Verify Repair</a>
            <a href="/maintenance/action?action=reopen_task&id={esc(record_id)}">Reopen Maintenance Task</a></div>"""
        readiness = "".join(
            f'<option value="{v}">{v.replace("_", " ").title()}</option>'
            for v in sorted(MaintenanceWorkflow.READINESS)
        )
        return self._shell(
            action.replace("_", " ").title(),
            f"""<section class="page-heading"><div><p class="eyebrow">Controlled workflow</p>
            <h1>{esc(action.replace("_", " ").title())}</h1>
            <p>This page creates a zero-write preview before permanent commit.</p></div></section>
            {workflow_links}<section class="panel"><form class="receive-form" method="post"
            action="/maintenance/review"><input type="hidden" name="action" value="{esc(action)}">
            {fields}<label><span>Equipment readiness</span><select name="readiness_state">
            {readiness}</select></label><label class="choice"><input type="checkbox"
            name="unattended_printing_allowed" value="yes"><span>Unattended printing is allowed</span></label>
            <label><span>Actor</span><input name="actor" value="Cowboy" required></label>
            <button type="submit">Review maintenance change</button></form></section>""",
            '<a href="/">Dashboard</a> / <a href="/maintenance">Maintenance</a> / Workflow',
        )

    def _maintenance_review(self, review: dict) -> str:
        values = review["values"]
        labels = {"action", "event_type", "status", "severity", "readiness_state"}
        summary = "".join(
            f"<div><dt>{esc(k.replace('_', ' ').title())}</dt><dd>"
            f"{display(v.replace('_', ' ').title() if k in labels and isinstance(v, str) else v)}"
            f"</dd></div>"
            for k, v in values.items()
            if k not in {"version", "module", "reviewed_at", "request_nonce", "actor"}
        )
        return self._shell(
            "Review Maintenance Change",
            f"""<section class="page-heading"><div><p class="eyebrow">Zero-write preview</p>
            <h1>Review Maintenance Change</h1><p>No production data has been written yet.</p></div></section>
            <section class="panel"><dl class="detail-list">{summary}</dl>
            <form method="post" action="/maintenance/confirm">
            <input type="hidden" name="review_token" value="{esc(review["token"])}">
            <label class="confirmation"><input type="checkbox" name="confirm"
            value="maintenance-write" required><span>I approve this permanent maintenance
            registry write and immutable audit entry.</span></label>
            <button type="submit">Commit maintenance change</button></form></section>""",
            '<a href="/">Dashboard</a> / <a href="/maintenance">Maintenance</a> / Review',
        )

    def _maintenance_complete(self, result: dict) -> str:
        return self._shell(
            "Maintenance Recorded",
            f"""<section class="success-panel"><p class="eyebrow">Committed</p>
            <h1>{esc(result["event_number"])}</h1><p>The maintenance change and immutable
            history entry #{result["history_id"]} were committed atomically.</p>
            <a class="primary-link" href="/maintenance">View maintenance history</a></section>""",
            '<a href="/">Dashboard</a> / <a href="/maintenance">Maintenance</a> / Recorded',
        )

    def _maintenance_evidence_form(self, query: dict[str, str]) -> str:
        return self._shell(
            "Add Maintenance Evidence",
            f"""<section class="page-heading"><div><p class="eyebrow">SHA-256 evidence</p>
            <h1>Add Maintenance Evidence</h1><p>The original file stays in place; the registry
            stores its absolute path and cryptographic fingerprint.</p></div></section>
            <section class="panel"><form class="receive-form" method="post"
            action="/maintenance/evidence"><label><span>Maintenance record ID</span>
            <input name="record_id" type="number" min="1" value="{esc(query.get("id", ""))}" required></label>
            <label><span>Evidence type</span><select name="evidence_type">
            <option value="photo">Photo</option><option value="video">Video</option></select></label>
            <label><span>Absolute file path</span><input name="file_path" required></label>
            <label><span>Caption</span><input name="caption"></label>
            <label><span>Captured at (optional RFC3339)</span><input name="captured_at"></label>
            <label><span>Actor</span><input name="actor" value="Cowboy" required></label>
            <label class="confirmation"><input type="checkbox" name="confirm"
            value="maintenance-evidence" required><span>I verified this file and approve
            permanent SHA-256 evidence registration.</span></label>
            <button type="submit">Register evidence</button></form></section>""",
            '<a href="/">Dashboard</a> / <a href="/maintenance">Maintenance</a> / Evidence',
        )

    def _maintenance_evidence_complete(self, form: dict[str, str]) -> str:
        try:
            record_id = int(form.get("record_id", ""))
        except (TypeError, ValueError) as exc:
            raise MaintenanceError("maintenance record ID is invalid") from exc
        result = self.maintenance.add_evidence(
            record_id, evidence_type=form.get("evidence_type", ""),
            file_path=form.get("file_path", ""), actor=form.get("actor", ""),
            caption=form.get("caption"), captured_at=form.get("captured_at") or None,
        )
        return self._shell(
            "Maintenance Evidence Recorded",
            f"""<section class="success-panel"><p class="eyebrow">Committed</p>
            <h1>{esc(result["event_number"])}</h1><p>Evidence #{result["id"]} was registered
            with SHA-256 {esc(result["sha256"])}.</p>
            <a class="primary-link" href="/maintenance">Return to backlog</a></section>""",
            '<a href="/">Dashboard</a> / <a href="/maintenance">Maintenance</a> / Evidence recorded',
        )

    def _maintenance_error(self, message: str) -> str:
        return self._error_page("Maintenance workflow stopped", message, status="Not recorded")

    def _projects(self) -> str:
        with closing(connect(self.database)) as db:
            rows = db.execute(
                """SELECT * FROM projects WHERE archived_at IS NULL ORDER BY updated_at DESC,id"""
            ).fetchall()
        cards = "".join(
            f"""<article class="order-card"><h2>{esc(r["name"])}</h2>
            <p><strong>{esc(r["progress_mode"].title())}</strong> ·
            {display(r["progress_stage"], "No stage recorded")}</p>
            <p>{display(r["progress_note"], "No progress note")}</p></article>"""
            for r in rows
        ) or "<p>No projects recorded.</p>"
        return self._shell(
            "Projects",
            f'<section class="page-heading"><div><p class="eyebrow">Projects</p><h1>Project Progress</h1>'
            f'<p>Exact, estimated, stage-only, or honestly unknown.</p></div></section>'
            f'<section class="order-list">{cards}</section>',
            '<a href="/">Dashboard</a> / Projects',
        )

    def _audit_mode(self) -> str:
        rows = ProductionService.audit_history(self.database)
        history = "".join(
            f"""<tr><td data-label="When">{esc(r["occurred_at"])}</td>
            <td data-label="Who">{esc(r["actor"])}</td><td data-label="Module">{esc(r["module"])}</td>
            <td data-label="Event">{esc(r["event_type"])}</td>
            <td data-label="Entity">{esc(r["entity_human_id"] or r["entity_type"])}</td>
            <td data-label="Summary">{esc(r["summary"])}</td></tr>""" for r in rows
        ) or '<tr><td colspan="6">No Stage 2 audit events yet.</td></tr>'
        return self._shell(
            "Audit Mode",
            f"""<section class="page-heading"><div><p class="eyebrow">Read only</p>
            <h1>Audit Mode</h1><p>Permanent history. This screen cannot edit or delete records.</p></div></section>
            <section class="panel table-panel"><table><thead><tr><th>When</th><th>Who</th>
            <th>Module</th><th>Event</th><th>Entity</th><th>Summary</th></tr></thead>
            <tbody>{history}</tbody></table></section>""",
            '<a href="/">Dashboard</a> / Audit Mode',
        )

    def _production_error(self, message: str) -> str:
        return self._error_page("Production workflow stopped", message, status="Not recorded")

    def _shell(self, title: str, content: str, breadcrumb: str, *, description="") -> str:
        nav = []
        for section, links in NAVIGATION:
            nav.append(f'<section class="nav-section"><h2>{esc(section)}</h2><ul>')
            for label, path in links:
                nav.append(f'<li><a href="{esc(path)}">{esc(label)}</a></li>')
            nav.append("</ul></section>")
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#111111">
  <title>{esc(title)} · THS Inventory System</title>
  <link rel="stylesheet" href="/static/style.css?v=8">
  <script src="/static/app.js?v=1" defer></script>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="topbar">
    <button class="nav-toggle" type="button" aria-controls="site-navigation"
      aria-expanded="false"><span aria-hidden="true">☰</span><span>Menu</span></button>
    <a class="brand" href="/"><span class="brand-mark">THS</span>
      <span><strong>Inventory System</strong><small>THS Command Center</small></span></a>
    <details class="workflow-menu">
      <summary>Controlled workflows</summary>
      <div class="workflow-menu-panel">
        <p>Inventory actions</p>
        <a href="/inventory/filament/ams/initialize">
          <strong>Initialize Verified AMS Slot</strong>
          <span>Record one physically verified spool assignment.</span>
        </a>
        <a href="/inventory/filament/replace">
          <strong>Replace Active Filament Spool</strong>
          <span>Empty, open, and load through one guided workflow.</span>
        </a>
        <a href="/inventory/filament/receive">
          <strong>Receive Verified Sealed Spool</strong>
          <span>Add one verified sealed physical spool.</span>
        </a>
        <a href="/inventory/filament/ams/return">
          <strong>Return AMS Spool to Storage</strong>
          <span>Unload one active spool without changing its recorded quantity.</span>
        </a>
        <a href="/orders">
          <strong>Receive Pending Order</strong>
          <span>Select a delivered order and preview its verified receipt.</span>
        </a>
        <a href="/inventory/filament/register-open">
          <strong>Register Existing Open Spool</strong>
          <span>Add legacy open inventory without assuming 1,000 g.</span>
        </a>
        <span class="workflow-menu-future" aria-disabled="true">
          <strong>Inventory Adjustments</strong><span>Future · admin only</span>
        </span>
      </div>
    </details>
  </header>
  <div class="app-layout">
    <nav class="sidebar" id="site-navigation" aria-label="Main navigation">
      {''.join(nav)}
    </nav>
    <main id="main-content" tabindex="-1">
      <div class="breadcrumb" aria-label="Breadcrumb">{breadcrumb}</div>
      <div class="page-heading"><div><p class="eyebrow">THS Inventory System</p>
        <h1>{esc(title)}</h1>{f'<p>{esc(description)}</p>' if description else ''}</div></div>
      {content}
    </main>
  </div>
  <footer><span>Local-first workshop inventory</span><span>Database: {esc(self.database.name)}</span></footer>
</body>
</html>"""

    def _dashboard(self) -> str:
        t = self.queries.dashboard()
        cards = [
            ("Active physical spools", t["physical_spools"] - t["archived_spools"], "spools"),
            ("Sealed spools", t["sealed_spools"], "sealed"),
            ("Open spools", t["open_spools"], "open"),
            ("AMS-loaded spools", t["loaded_spools"], "loaded"),
            ("Empty or archived", t["archived_spools"], "retained in history"),
            ("Catalog products", t["catalog_products"], "grouped products"),
            ("Nominal/original weight", kilograms(t["nominal_grams"]), grams(t["nominal_grams"])),
            ("Estimated remaining", kilograms(t["remaining_grams"]), grams(t["remaining_grams"])),
            ("Reserved weight", kilograms(t["reserved_grams"]), grams(t["reserved_grams"])),
            ("Available weight", kilograms(t["available_grams"]), grams(t["available_grams"])),
            ("AMS units", t["ams_units"], f'{t["total_slots"]} total slots'),
            ("Occupied AMS slots", t["occupied_slots"], f'{t["empty_slots"]} empty slots'),
            ("Low-stock products", t["low_stock_products"], "No arbitrary thresholds"),
        ]
        card_html = "".join(
            f'<article class="metric-card"><h2>{esc(label)}</h2>'
            f'<strong>{esc(value)}</strong><p>{esc(note)}</p></article>'
            for label, value, note in cards
        )
        brands = "".join(
            f'<li><span>{esc(row["manufacturer"])}</span><strong>{row["spool_count"]} spools</strong></li>'
            for row in t["brand_totals"]
        )
        content = f"""
        <section class="workflow-hub" aria-labelledby="workflow-hub-title">
          <div class="section-heading"><div><h2 id="workflow-hub-title">Controlled workflows</h2>
            <p>Start verified inventory actions here. No route memorization required.</p></div></div>
          <div class="workflow-grid">
            <a class="workflow-card" href="/inventory/filament/ams/initialize">
              <span class="workflow-number">01</span><div>
              <h3>Initialize Verified AMS Slot</h3>
              <p>Place one identified Sealed or Open spool into its physically verified AMS slot.</p>
              <strong>Start workflow →</strong></div>
            </a>
            <a class="workflow-card" href="/inventory/filament/replace">
              <span class="workflow-number">02</span><div>
              <h3>Replace Active Filament Spool</h3>
              <p>Mark the active spool Empty, open its sealed replacement, and load it atomically.</p>
              <strong>Start workflow →</strong></div>
            </a>
            <a class="workflow-card" href="/inventory/filament/receive">
              <span class="workflow-number">03</span><div>
              <h3>Receive Verified Sealed Spool</h3>
              <p>Receive one verified sealed spool with review and explicit confirmation.</p>
              <strong>Start workflow →</strong></div>
            </a>
            <a class="workflow-card" href="/inventory/filament/ams/return">
              <span class="workflow-number">04</span><div>
              <h3>Return AMS Spool to Storage</h3>
              <p>Unload one active spool to verified storage without changing its remaining weight.</p>
              <strong>Start workflow →</strong></div>
            </a>
            <a class="workflow-card" href="/inventory/filament/register-open">
              <span class="workflow-number">05</span><div>
              <h3>Register Existing Open Spool</h3>
              <p>Add one legacy open spool with exact, estimated, or unknown remaining quantity.</p>
              <strong>Start workflow →</strong></div>
            </a>
            <article class="workflow-card future" aria-disabled="true">
              <span class="workflow-number">06</span><div>
              <h3>Inventory Adjustments</h3><p>Planned administrator-only workflow.</p>
              <strong>Future · admin only</strong></div>
            </article>
          </div>
        </section>
        <section aria-labelledby="summary-title"><div class="section-heading">
          <div><h2 id="summary-title">Filament at a glance</h2>
          <p>Live totals from the migrated SQLite inventory database.</p></div>
          <a class="primary-link" href="/inventory/filament">Browse filament</a>
        </div><div class="metric-grid">{card_html}</div></section>
        <div class="content-grid">
          <section class="panel"><h2>Physical spools by brand</h2><ul class="stat-list">{brands}</ul></section>
          <section class="panel"><h2>Reorder status</h2>
            <p class="status-line"><span class="status neutral">No reorder rule set</span></p>
            <p>There are no configured filament minimums, so the system shows zero low-stock alerts.</p>
          </section>
        </div>"""
        return self._shell(
            "Dashboard", content, '<span aria-current="page">Overview / Dashboard</span>',
            description="Real inventory totals. No estimated workshop stock has been invented.",
        )

    def _operational_dashboard(self) -> str:
        t = self.queries.dashboard()
        cards = [
            ("Active physical spools", t["physical_spools"] - t["archived_spools"], "spools"),
            ("Sealed spools", t["sealed_spools"], "sealed"),
            ("AMS-loaded spools", t["loaded_spools"], "loaded"),
            ("Catalog products", t["catalog_products"], "grouped products"),
            ("Available weight", kilograms(t["available_grams"]), grams(t["available_grams"])),
            ("AMS occupancy", f'{t["occupied_slots"]}/{t["total_slots"]}', f'{t["empty_slots"]} empty slots'),
        ]
        card_html = "".join(
            f'<article class="metric-card"><h2>{esc(label)}</h2>'
            f'<strong>{esc(value)}</strong><p>{esc(note)}</p></article>'
            for label, value, note in cards
        )
        health = t["shop_health"]
        signals = "".join(
            f'<span class="signal-light {name}{" active" if health["signal"] == name else ""}"'
            f' aria-label="{label}"></span>'
            for name, label in (("red", "Red"), ("yellow", "Yellow"), ("green", "Green"))
        )
        restrictions = (
            "".join(
                f"""<li><div><strong>{esc(item["equipment"])}</strong>
                <span>{esc(item["readiness_label"])}</span></div>
                {f'<span>Maintenance: <a href="{esc(item["href"])}">{esc(item["maintenance_number"])}</a></span>' if item.get("maintenance_number") else ''}
                {f'<span>Severity: {esc(item["severity"].replace("_", " ").title())}</span>' if item.get("severity") else ''}
                {f'<span>Status: {esc(item["status"].replace("_", " ").title())}</span>' if item.get("status") else ''}
                {f'<span>{esc(item["message"])}</span>' if item.get("message") else ''}</li>"""
                for item in health["restrictions"]
            )
            if health["restrictions"]
            else "<li>All relevant equipment readiness states are normal. No active operational restrictions.</li>"
        )
        printer = t["printer"]
        freshness = (
            '<span class="status warning">Stale · manual refresh required</span>'
            if printer and printer["status_stale"]
            else '<span class="status good">Current</span>'
        )
        ams_slots = "".join(
            f"""<li class="dashboard-slot"><span>{esc(slot["equipment"])} · Slot {slot["slot_number"]}</span>
            <strong>{esc(slot["permanent_id"] or "Empty")}</strong>
            {f'<small><i class="color-swatch" style="--swatch:{self._swatch(slot["color"])}"></i>{esc(slot["manufacturer"])} · {esc(slot["color"])} · {grams(slot["remaining_quantity"])}</small>' if slot["permanent_id"] else '<small>Available</small>'}</li>"""
            for slot in t["ams_details"]
        )
        pending_orders = (
            "".join(
                f"""<article class="compact-order"><div><span class="status neutral">{esc(order["state"].title())}</span>
                <h3>{esc(order["description"])}</h3><p>{esc(order["supplier"])} ·
                {order["expected_quantity"]} {esc(order["unit_label"])} · {esc(order["material"])} ·
                <i class="color-swatch" style="--swatch:{self._swatch(order["color"])}"></i>{esc(order["color"])}</p>
                </div><a href="/orders/{order["id"]}/receive">Review receipt</a></article>"""
                for order in t["pending_orders"]
            ) if t["pending_orders"] else "<p>No pending orders.</p>"
        )
        activity_labels = {
            "load_instance_into_ams": "Spool loaded into AMS",
            "open_sealed_spool": "Sealed spool opened",
            "mark_spool_empty": "Spool marked Empty",
            "add_individual_instance": "Physical spool received",
            "receive_order_batch": "Order receipt committed",
            "transition_order": "Order status changed",
        }
        recent = (
            "".join(
                f"""<li><div><strong>{esc(activity_labels.get(action["action_type"], action["action_type"]))}</strong>
                <span>{esc(action["affected_human_id"] or "Inventory")}</span></div>
                <small>{esc(action["actor"])} · {esc(action["occurred_at"])}</small></li>"""
                for action in t["recent_activity"]
            ) if t["recent_activity"] else "<li>No controlled inventory activity recorded yet.</li>"
        )
        content = f"""
        <section class="alert-panel health-{health["signal"]}" aria-labelledby="warning-title">
          <div class="health-heading"><div class="traffic-signal" role="img"
            aria-label="{esc(health["label"])}">{signals}</div>
            <div><p class="eyebrow">Shop health</p><h2 id="warning-title">{esc(health["label"])}</h2></div>
          </div><ul class="health-restrictions">{restrictions}</ul></section>
        <section class="ops-section" aria-labelledby="printer-title"><div class="section-heading">
          <div><h2 id="printer-title">Printer status</h2><p>Source and freshness are always explicit.</p></div>{freshness}</div>
          <article class="printer-card"><div><p class="eyebrow">{esc(printer["manufacturer"] if printer else "")} {esc(printer["model"] if printer else "")}</p>
            <h3>{esc(printer["name"] if printer else "No printer")}</h3></div>
            <dl class="compact-stats"><div><dt>Status</dt><dd>{esc(printer["status"].title() if printer else "Not configured")}</dd></div>
            <div><dt>Active job</dt><dd>{display(printer["active_job_name"] if printer else None, "No live job asserted")}</dd></div>
            <div><dt>Source</dt><dd>{esc(printer["status_source"].title() if printer else "None")}</dd></div>
            <div><dt>Last update</dt><dd>{display(printer["last_update_at"] if printer else None, "Never verified")}</dd></div></dl>
            <p>{display(printer["operational_note"] if printer else None)}</p></article></section>
        <section class="ops-section" aria-labelledby="ams-title"><div class="section-heading">
          <div><h2 id="ams-title">AMS occupancy and loaded filament</h2>
          <p>{t["occupied_slots"]} occupied · {t["empty_slots"]} empty</p></div>
          <a href="/inventory/filament/ams">View AMS details</a></div>
          <ul class="dashboard-slots">{ams_slots}</ul></section>
        <section class="ops-section" aria-labelledby="orders-title"><div class="section-heading">
          <div><h2 id="orders-title">Pending orders</h2><p>Expected stock is not physical inventory.</p></div>
          <a href="/orders">View all orders</a></div><div class="order-list">{pending_orders}</div></section>
        <section class="ops-section" aria-labelledby="low-title"><div class="section-heading">
          <div><h2 id="low-title">Low stock</h2><p>Only configured thresholds create warnings.</p></div></div>
          <div class="panel"><span class="status {"warning" if t["low_stock_products"] else "neutral"}">
          {t["low_stock_products"]} low-stock products</span>
          <p>{"Review configured reorder rules." if t["low_stock_products"] else "No configured product is below its threshold."}</p></div></section>
        <section aria-labelledby="summary-title"><div class="section-heading">
          <div><h2 id="summary-title">Shop totals</h2><p>Live inventory totals.</p></div>
          <a class="primary-link" href="/inventory/filament">Browse filament</a>
        </div><div class="metric-grid">{card_html}</div></section>
        <section class="ops-section" aria-labelledby="activity-title"><div class="section-heading">
          <div><h2 id="activity-title">Recent activity</h2><p>Latest useful immutable actions only.</p></div></div>
          <ul class="activity-list">{recent}</ul></section>"""
        return self._shell(
            "Dashboard", content, '<span aria-current="page">Overview / Dashboard</span>',
            description="What is happening in the shop right now.",
        )

    @staticmethod
    def _swatch(color) -> str:
        normalized = " ".join(str(color or "").strip().lower().split())
        return {
            "white": "#f4f4f0", "jade white": "#f4f4f0",
            "orange": "#ff7a18", "red": "#d32f2f", "black": "#24262a",
            "cyan": "#0086d6", "cayenne": "#0086d6",
            "blue": "#2878d0", "cobalt blue": "#2454a6", "brown": "#79533a",
            "gray": "#8a9098", "dark gray": "#4b5057", "pink": "#ef8cab",
            "gold": "#d5a72e", "turquoise": "#27b8b2", "bambu green": "#00ae42",
        }.get(normalized, "#777d86")

    def _filament_inventory(self, query: dict[str, list[str]]) -> str:
        get = lambda key: query.get(key, [""])[0]
        search, state = get("q"), get("state")
        manufacturer, material, sort = get("manufacturer"), get("material"), get("sort") or "manufacturer"
        low_stock = get("low_stock") == "1"
        data = self.queries.grouped_filament(
            search=search, state=state, manufacturer=manufacturer,
            material=material, low_stock=low_stock, sort=sort,
        )
        options = lambda values, selected: "".join(
            f'<option value="{esc(v)}"{" selected" if v == selected else ""}>{esc(v)}</option>'
            for v in values
        )
        rows = []
        for p in data["products"]:
            reorder = (
                '<span class="status warning">Low stock</span>'
                if p["has_low_stock"]
                else (
                    '<span class="status good">Stock rule OK</span>'
                    if p["minimum_quantity"] is not None
                    else '<span class="status neutral">No reorder rule set</span>'
                )
            )
            rows.append(f"""
            <article class="product-card">
              <div class="product-title"><div><p class="eyebrow">{esc(p["manufacturer"])}</p>
                <h2><a href="/inventory/filament/products/{p["id"]}">{esc(p["product_line"])} — {esc(p["color"])}</a></h2>
                <p>{esc(p["material"])}</p></div>{reorder}</div>
              <dl class="compact-stats">
                <div><dt>Spools</dt><dd>{p["physical_spools"]}</dd></div>
                <div><dt>Sealed</dt><dd>{p["sealed_spools"]}</dd></div>
                <div><dt>Open</dt><dd>{p["open_spools"]}</dd></div>
                <div><dt>Loaded</dt><dd>{p["loaded_spools"]}</dd></div>
                <div><dt>Empty / archived</dt><dd>{p["empty_archived_spools"]}</dd></div>
                <div><dt>Nominal</dt><dd>{grams(p["nominal_grams"])}</dd></div>
                <div><dt>Remaining</dt><dd>{grams(p["remaining_grams"])}</dd></div>
                <div><dt>Reserved</dt><dd>{grams(p["reserved_grams"])}</dd></div>
                <div><dt>Available</dt><dd>{grams(p["available_grams"])}</dd></div>
              </dl>
            </article>""")
        result = (
            "".join(rows)
            if rows
            else '<div class="empty-state"><h2>No filament found</h2>'
                 "<p>Try clearing one or more search filters.</p></div>"
        )
        content = f"""
        <form class="filter-panel" method="get" action="/inventory/filament" role="search">
          <label class="search-field"><span>Search inventory</span>
            <input type="search" name="q" value="{esc(search)}"
              placeholder="Brand, material, color, product line, THS-FIL ID or notes">
          </label>
          <label><span>State</span><select name="state">
            <option value="">All states</option>
            {options(["sealed","open","loaded","empty","archived"],state)}
          </select></label>
          <label><span>Manufacturer</span><select name="manufacturer">
            <option value="">All manufacturers</option>{options(data["manufacturers"],manufacturer)}
          </select></label>
          <label><span>Material</span><select name="material">
            <option value="">All materials</option>{options(data["materials"],material)}
          </select></label>
          <label><span>Sort</span><select name="sort">
            {options(["manufacturer","material","color","spools","available","low_stock"],sort)}
          </select></label>
          <label class="check-field"><input type="checkbox" name="low_stock" value="1"
            {"checked" if low_stock else ""}><span>Low stock only</span></label>
          <div class="filter-actions"><button type="submit">Apply filters</button>
            <a href="/inventory/filament">Clear</a></div>
        </form>
        <div class="result-heading" aria-live="polite"><strong>{len(data["products"])} grouped products</strong>
          <span>One card per catalog product</span>
          <span class="inline-actions"><a href="/inventory/filament/receive">Receive sealed spool</a>
          <a class="primary-link" href="/inventory/filament/replace">Replace active spool</a></span></div>
        <section class="product-grid" aria-label="Grouped filament products">{result}</section>"""
        return self._shell(
            "Filament Inventory", content,
            '<a href="/">Dashboard</a> / <span aria-current="page">Filament Inventory</span>',
            description="Grouped by manufacturer, product line, and color. Select a product to inspect its physical spools.",
        )

    def _receive_form(self) -> str:
        options = self.receiving.options()
        products = "".join(
            f'<option value="{p["id"]}">{esc(p["manufacturer"])} — '
            f'{esc(p["product_line"])} — {esc(p["color"])} '
            f'({esc(p["material"])}, {esc(p["diameter_mm"])} mm, '
            f'{grams(p["nominal_weight_g"])})</option>'
            for p in options["products"]
        )
        locations = "".join(
            f'<option value="{row["id"]}">{esc(row["name"])}</option>'
            for row in options["locations"]
        )
        content = f"""
        <div class="notice"><strong>Narrow verified workflow</strong>
          <p>This creates one new sealed physical spool. It cannot edit existing inventory.</p></div>
        <form class="receive-form" method="post" action="/inventory/filament/receive/review">
          <fieldset><legend>1. Catalog product</legend>
            <label class="choice"><input type="radio" name="product_mode" value="existing" checked>
              <span><strong>Select an existing product</strong><small>Use its verified catalog specifications.</small></span>
            </label>
            <label><span>Existing catalog product</span><select name="catalog_item_id">
              <option value="">Select a product</option>{products}</select></label>
            <div class="form-divider"><span>Or create a verified product if it does not exist</span></div>
            <label class="choice"><input type="radio" name="product_mode" value="new">
              <span><strong>Create a new verified catalog product</strong>
                <small>Every field below must be checked against the spool packaging.</small></span>
            </label>
            <div class="form-grid">
              <label><span>Manufacturer</span><input name="manufacturer" maxlength="120"></label>
              <label><span>Product line</span><input name="product_line" maxlength="120"></label>
              <label><span>Material</span><input name="material" maxlength="80"></label>
              <label><span>Manufacturer color</span><input name="color" maxlength="120"></label>
              <label><span>Diameter (mm)</span><input name="diameter_mm" type="number"
                min="1" max="10" step="0.01" inputmode="decimal"></label>
              <label><span>Nominal filament weight (g)</span><input name="nominal_weight_g"
                type="number" min="1" max="100000" step="0.01" inputmode="decimal"></label>
            </div>
          </fieldset>
          <fieldset><legend>2. Verified receiving details</legend><div class="form-grid">
            <label><span>Initial location</span><select name="location_id" required>
              <option value="">Select storage location</option>{locations}</select></label>
            <label><span>Actor</span><input name="actor" value="Cowboy" maxlength="100" required></label>
            <label class="wide-field"><span>Reason or receiving note (optional)</span>
              <textarea name="reason" maxlength="500" rows="3"></textarea></label>
          </div></fieldset>
          <div class="notice subdued"><strong>Fixed by this workflow</strong>
            <p>Status: Sealed · Condition: New · Verified: Yes · Module: {esc(self.receiving.MODULE)}</p></div>
          <div class="form-actions"><a href="/inventory/filament">Cancel</a>
            <button type="submit">Review before receiving</button></div>
        </form>"""
        return self._shell(
            "Receive a Verified Sealed Spool", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">Receive spool</span>',
            description="One carefully validated physical spool at a time.",
        )

    def _receive_review(self, review) -> str:
        v = review.values
        fields = (
            ("Manufacturer", v["manufacturer"]),
            ("Product Line", v["product_line"]),
            ("Material", v["material"]),
            ("Color", v["color"]),
            ("Diameter", f'{v["diameter_mm"]:g} mm'),
            ("Nominal Weight", grams(v["nominal_weight_g"])),
            ("Initial Status", "Sealed"),
            ("Initial Location", v["location"]),
            ("Generated THS-FIL ID", v["permanent_id"]),
            ("Actor", v["actor"]),
            ("Module", v["module"]),
            ("Optional Reason", v["reason"] or "No reason provided"),
        )
        details = "".join(
            f"<div><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>"
            for label, value in fields
        )
        content = f"""
        <div class="notice"><strong>Nothing has been written yet</strong>
          <p>Check every value below. The permanent ID is reserved only when you confirm.</p></div>
        <section class="panel review-panel"><h2>Spool receiving review</h2>
          <dl class="detail-list">{details}</dl></section>
        <form class="confirm-form" method="post" action="/inventory/filament/receive/confirm">
          <input type="hidden" name="review_token" value="{esc(review.token)}">
          <label class="choice confirm-choice"><input type="checkbox" name="confirm"
            value="receive" required><span><strong>I verified these values against the physical spool.</strong>
            <small>Confirming creates the spool, transaction, and immutable audit record.</small></span></label>
          <div class="form-actions"><a href="/inventory/filament/receive">Go back without saving</a>
            <button type="submit">Confirm and receive spool</button></div>
        </form>"""
        return self._shell(
            f'Review {v["permanent_id"]}', content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<a href="/inventory/filament/receive">Receive spool</a> / '
            '<span aria-current="page">Review</span>',
        )

    def _receive_complete(self, result: dict) -> str:
        content = f"""
        <div class="success-panel"><p class="eyebrow">Inventory action completed</p>
          <h2>{esc(result["permanent_id"])} was received</h2>
          <p>One verified sealed physical spool now exists in {esc(result["location"])}.</p></div>
        <div class="detail-grid">
          <section class="panel"><h2>Received spool</h2><dl class="detail-list">
            <div><dt>Permanent ID</dt><dd><strong>{esc(result["permanent_id"])}</strong></dd></div>
            <div><dt>Product</dt><dd>{esc(result["manufacturer"])} ·
              {esc(result["product_line"])} · {esc(result["color"])}</dd></div>
            <div><dt>Status</dt><dd>Sealed</dd></div>
            <div><dt>Location</dt><dd>{esc(result["location"])}</dd></div>
            <div><dt>Nominal weight</dt><dd>{grams(result["nominal_weight_g"])}</dd></div>
          </dl></section>
          <section class="panel"><h2>Recorded history</h2><dl class="detail-list">
            <div><dt>Actor</dt><dd>{esc(result["actor"])}</dd></div>
            <div><dt>Module</dt><dd>{esc(result["module"])}</dd></div>
            <div><dt>Inventory transaction</dt><dd>#{result["transaction_id"]}</dd></div>
            <div><dt>Immutable audit action</dt><dd>#{result["action_id"]}</dd></div>
            <div><dt>Recorded</dt><dd>{esc(result["occurred_at"])}</dd></div>
            <div><dt>Reason</dt><dd>{display(result["reason"], "No reason provided")}</dd></div>
          </dl></section>
        </div>
        <div class="form-actions"><a href="/inventory/filament/receive">Receive another spool</a>
          <a class="primary-link" href="/inventory/filament/spools/{result["instance_id"]}">
            View {esc(result["permanent_id"])}</a></div>"""
        return self._shell(
            f'Received {result["permanent_id"]}', content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">Receive complete</span>',
        )

    def _receive_error(self, message: str) -> str:
        content = f"""<section class="empty-state"><p class="eyebrow">Not received</p>
          <h2>Spool was not added</h2><p>{esc(message)}</p>
          <a class="primary-link" href="/inventory/filament/receive">Return to receiving form</a>
          </section>"""
        return self._shell(
            "Receive spool error", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">Receive error</span>',
        )

    def _replacement_form(self, filters: dict[str, str]) -> str:
        data = self.replacement.options(filters)
        filter_options = lambda values, selected: "".join(
            f'<option value="{esc(value)}"{" selected" if value == selected else ""}>'
            f'{esc(value)}</option>' for value in values
        )
        current_options = "".join(
            f'<option value="{s["id"]}">{esc(s["permanent_id"])} — '
            f'{esc(s["manufacturer"])} {esc(s["product_line"])} {esc(s["color"])} — '
            f'{esc(s["equipment_name"])} Slot {s["slot_number"]}</option>'
            for s in data["current_spools"]
        )
        replacement_options = "".join(
            f'<option value="{s["id"]}">{esc(s["permanent_id"])} — '
            f'{esc(s["manufacturer"])} {esc(s["product_line"])} {esc(s["color"])} — '
            f'{esc(s["material"])}</option>'
            for s in data["replacement_spools"]
        )
        slot_options = "".join(
            f'<option value="{slot["id"]}">{esc(slot["equipment_name"])} '
            f'Slot {slot["slot_number"]}'
            f'{" — occupied by " + esc(slot["occupant_permanent_id"]) if slot["occupant_permanent_id"] else " — empty"}'
            f'</option>' for slot in data["slots"]
        )
        no_active = (
            '<div class="notice subdued"><strong>No active AMS spool found</strong>'
            '<p>Load a verified spool into an AMS before using this workflow.</p></div>'
            if not data["current_spools"] else ""
        )
        content = f"""
        <div class="notice"><strong>One guided, atomic shop operation</strong>
          <p>The outgoing spool is emptied, one sealed spool is opened, and that replacement is loaded.
          Existing inventory cannot be generally edited here.</p></div>
        {no_active}
        <form class="filter-panel compact-filter" method="get"
          action="/inventory/filament/replace" role="search">
          <label class="search-field"><span>Find sealed replacement</span>
            <input type="search" name="q" value="{esc(data["filters"]["q"])}"
              placeholder="THS-FIL ID, manufacturer, material, or color"></label>
          <label><span>Manufacturer</span><select name="manufacturer">
            <option value="">All manufacturers</option>
            {filter_options(data["manufacturers"], data["filters"]["manufacturer"])}</select></label>
          <label><span>Material</span><select name="material">
            <option value="">All materials</option>
            {filter_options(data["materials"], data["filters"]["material"])}</select></label>
          <label><span>Color</span><select name="color"><option value="">All colors</option>
            {filter_options(data["colors"], data["filters"]["color"])}</select></label>
          <div class="filter-actions"><button type="submit">Filter sealed spools</button>
            <a href="/inventory/filament/replace">Clear</a></div>
        </form>
        <form class="receive-form replacement-form" method="post"
          action="/inventory/filament/replace/review">
          <fieldset><legend>1. Select the currently active spool</legend>
            <label><span>Loaded spool</span><select name="current_instance_id" required>
              <option value="">Select the spool currently installed</option>
              {current_options}</select></label>
            <label class="choice confirm-choice"><input type="checkbox"
              name="confirm_empty" value="yes" required>
              <span><strong>This spool is now empty.</strong>
              <small>The spool will be removed from its active AMS slot and archived as Empty.</small></span>
            </label>
          </fieldset>
          <fieldset><legend>2. Select a sealed replacement</legend>
            <label><span>Eligible sealed spool</span><select name="replacement_instance_id" required>
              <option value="">Select one sealed physical spool</option>
              {replacement_options}</select></label>
            <p class="field-help">{len(data["replacement_spools"])} sealed spool(s) match the current filters.</p>
          </fieldset>
          <fieldset><legend>3. Confirm the destination</legend>
            <label><span>AMS destination</span><select name="destination_slot_id">
              <option value="">Same AMS unit and slot as the outgoing spool (default)</option>
              {slot_options}</select></label>
            <p class="field-help">Choose another slot only if the replacement was physically installed there.
              Occupied slots are rejected unless occupied by the outgoing spool.</p>
            <div class="form-grid">
              <label><span>Actor</span><input name="actor" value="Cowboy"
                maxlength="100" required></label>
              <label><span>Purpose or reason (optional)</span>
                <input name="reason" maxlength="500"
                  placeholder="Project, print, or shop reason"></label>
            </div>
            <details class="optional-fields"><summary>Optional print-event notes</summary>
              <div class="form-grid">
                <label><span>Print or job name</span><input name="print_job_name"
                  maxlength="160" placeholder="Example: TweetyFixed"></label>
                <label><span>Approximate layer</span><input name="approximate_layer"
                  type="number" min="0" step="1" inputmode="numeric"></label>
                <label><span>Printer</span><input name="printer" maxlength="120"></label>
                <label><span>Plate</span><input name="plate" maxlength="120"></label>
                <label class="wide-field"><span>Free-form operational note</span>
                  <textarea name="operational_note" maxlength="1000" rows="3"></textarea></label>
              </div>
            </details>
          </fieldset>
          <div class="form-actions"><a href="/inventory/filament">Cancel</a>
            <button type="submit">Preview complete replacement</button></div>
        </form>"""
        return self._shell(
            "Replace Active Filament Spool", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">Replace active spool</span>',
            description="Empty, open, and load—three audited actions, one confirmed operation.",
        )

    def _replacement_review(self, review) -> str:
        v = review.values
        current, replacement, destination = (
            v["current"], v["replacement"], v["destination"]
        )
        content = f"""
        <div class="notice"><strong>Preview only — zero inventory writes</strong>
          <p>Confirm the physical IDs and destination. Inventory may change only after the final checkbox.</p></div>
        <section class="replacement-timeline" aria-label="Replacement operation preview">
          <article><span class="step-number">1</span><div><p>Unload and mark Empty</p>
            <h2>{esc(current["permanent_id"])}</h2>
            <span>{esc(current["manufacturer"])} · {esc(current["product_line"])} ·
              {esc(current["color"])}</span>
            <small>Currently {esc(current["equipment_name"])} Slot {current["slot_number"]}</small>
          </div></article>
          <span class="timeline-arrow" aria-hidden="true">↓</span>
          <article><span class="step-number">2</span><div><p>Open sealed replacement</p>
            <h2>{esc(replacement["permanent_id"])}</h2>
            <span>{esc(replacement["manufacturer"])} · {esc(replacement["product_line"])} ·
              {esc(replacement["color"])}</span><small>{esc(replacement["material"])}</small>
          </div></article>
          <span class="timeline-arrow" aria-hidden="true">↓</span>
          <article><span class="step-number">3</span><div><p>Load replacement</p>
            <h2>{esc(destination["equipment_name"])} Slot {destination["slot_number"]}</h2>
            <span>{esc(replacement["permanent_id"])}</span>
          </div></article>
        </section>
        <section class="panel review-panel"><h2>Operation context</h2><dl class="detail-list">
          <div><dt>Actor</dt><dd>{esc(v["actor"])}</dd></div>
          <div><dt>Module</dt><dd>{esc(v["module"])}</dd></div>
          <div><dt>Purpose or reason</dt><dd>{display(v["reason"], "No reason provided")}</dd></div>
          <div><dt>Print or job name</dt><dd>{display(v["print_job_name"])}</dd></div>
          <div><dt>Approximate layer</dt><dd>{display(v["approximate_layer"])}</dd></div>
          <div><dt>Printer</dt><dd>{display(v["printer"])}</dd></div>
          <div><dt>Plate</dt><dd>{display(v["plate"])}</dd></div>
          <div><dt>Operational note</dt><dd>{display(v["operational_note"])}</dd></div>
        </dl></section>
        <form class="confirm-form" method="post" action="/inventory/filament/replace/confirm">
          <input type="hidden" name="review_token" value="{esc(review.token)}">
          <label class="choice confirm-choice"><input type="checkbox" name="confirm"
            value="replace" required><span><strong>Perform this exact spool replacement.</strong>
            <small>All three actions succeed together or none are saved.</small></span></label>
          <div class="form-actions"><a href="/inventory/filament/replace">Go back without saving</a>
            <button type="submit">Confirm atomic replacement</button></div>
        </form>"""
        return self._shell(
            "Preview Spool Replacement", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<a href="/inventory/filament/replace">Replace active spool</a> / '
            '<span aria-current="page">Preview</span>',
        )

    def _replacement_complete(self, result: dict) -> str:
        current, replacement, destination = (
            result["current"], result["replacement"], result["destination"]
        )
        content = f"""
        <div class="success-panel"><p class="eyebrow">Atomic workflow completed</p>
          <h2>{esc(replacement["permanent_id"])} is loaded</h2>
          <p>{esc(current["permanent_id"])} is Empty. The sealed replacement was opened and loaded
          into {esc(destination["equipment_name"])} Slot {destination["slot_number"]}.</p></div>
        <div class="detail-grid">
          <section class="panel"><h2>Physical result</h2><dl class="detail-list">
            <div><dt>Outgoing spool</dt><dd>{esc(current["permanent_id"])} · Empty</dd></div>
            <div><dt>Replacement spool</dt><dd>{esc(replacement["permanent_id"])} · Loaded</dd></div>
            <div><dt>AMS destination</dt><dd>{esc(destination["equipment_name"])}
              Slot {destination["slot_number"]}</dd></div>
            <div><dt>Actor</dt><dd>{esc(result["actor"])}</dd></div>
            <div><dt>Reason</dt><dd>{display(result["reason"], "No reason provided")}</dd></div>
            <div><dt>Print or job name</dt><dd>{display(result["print_job_name"])}</dd></div>
            <div><dt>Approximate layer</dt><dd>{display(result["approximate_layer"])}</dd></div>
          </dl></section>
          <section class="panel"><h2>Immutable history</h2><dl class="detail-list">
            <div><dt>Parent workflow transaction</dt>
              <dd>#{result["workflow_transaction_id"]}</dd></div>
            <div><dt>Mark Empty action</dt><dd>#{result["empty_action_id"]}</dd></div>
            <div><dt>Open Sealed action</dt><dd>#{result["open_action_id"]}</dd></div>
            <div><dt>Load AMS action</dt><dd>#{result["load_action_id"]}</dd></div>
          </dl></section>
        </div>
        <div class="form-actions"><a href="/inventory/filament/replace">Replace another spool</a>
          <a class="primary-link" href="/inventory/filament/spools/{replacement["id"]}">
            View {esc(replacement["permanent_id"])}</a></div>"""
        return self._shell(
            "Spool Replacement Complete", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">Replacement complete</span>',
        )

    def _replacement_error(self, message: str) -> str:
        content = f"""<section class="empty-state"><p class="eyebrow">No changes saved</p>
          <h2>Spool replacement stopped</h2><p>{esc(message)}</p>
          <a class="primary-link" href="/inventory/filament/replace">Start a fresh replacement</a>
          </section>"""
        return self._shell(
            "Spool replacement stopped", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">Replacement stopped</span>',
        )

    def _initialization_form(self) -> str:
        data = self.initialization.options()
        spools = "".join(
            f'<option value="{s["id"]}">{esc(s["permanent_id"])} — '
            f'{esc(s["manufacturer"])} {esc(s["product_line"])} {esc(s["color"])} — '
            f'{esc(s["state"].title())}</option>' for s in data["spools"]
        )
        slots = "".join(
            f'<option value="{slot["id"]}"'
            f'{" disabled" if slot["occupant_instance_id"] is not None else ""}>'
            f'{esc(slot["equipment_name"])} Slot {slot["slot_number"]}'
            f'{" — occupied by " + esc(slot["occupant_permanent_id"]) if slot["occupant_permanent_id"] else " — empty"}'
            f'</option>' for slot in data["slots"]
        )
        content = f"""
        <div class="notice"><strong>Operational-readiness setup only</strong>
          <p>This establishes one verified physical spool in one existing AMS slot.
          It does not create inventory, edit weight, or provide general AMS management.</p></div>
        <form class="receive-form initialization-form" method="post"
          action="/inventory/filament/ams/initialize/review">
          <fieldset><legend>1. Select the identified physical spool</legend>
            <label><span>Eligible Sealed or Open spool</span><select name="instance_id" required>
              <option value="">Select one positively identified THS-FIL spool</option>
              {spools}</select></label>
            <p class="field-help">Empty, archived, inactive, and already-assigned spools are excluded.</p>
          </fieldset>
          <fieldset><legend>2. Select the verified physical AMS slot</legend>
            <label><span>AMS unit and slot</span><select name="slot_id" required>
              <option value="">Select the slot you physically verified</option>{slots}</select></label>
            <p class="field-help">Names and slot numbers come directly from configured equipment.</p>
          </fieldset>
          <fieldset><legend>3. Record when the loading actually occurred</legend>
            <div class="form-grid">
              <label><span>Effective workshop time</span><input type="datetime-local"
                name="effective_at" value="{esc(self.initialization.default_effective_local())}"
                required></label>
              <label><span>Actor</span><input name="actor" value="Cowboy"
                maxlength="100" required></label>
              <label class="wide-field"><span>Reason or verification note (optional)</span>
                <textarea name="reason" maxlength="500" rows="3"></textarea></label>
            </div>
            <label class="choice confirm-choice"><input type="checkbox"
              name="confirm_verified" value="yes" required>
              <span><strong>I physically verified this spool and AMS slot.</strong>
              <small>If the spool is Sealed, confirmation records Open before Loaded.</small></span>
            </label>
          </fieldset>
          <div class="form-actions"><a href="/inventory/filament/ams">Cancel</a>
            <button type="submit">Preview verified AMS assignment</button></div>
        </form>"""
        return self._shell(
            "Initialize Verified AMS State", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<a href="/inventory/filament/ams">AMS Units</a> / '
            '<span aria-current="page">Initialize verified state</span>',
            description="One identified spool, one physically verified slot, no invented history.",
        )

    def _initialization_review(self, review) -> str:
        v, spool, slot = review.values, review.values["spool"], review.values["slot"]
        transition = (
            "Sealed → Open → Loaded" if spool["state"] == "sealed" else "Open → Loaded"
        )
        content = f"""
        <div class="notice"><strong>Preview only — zero writes</strong>
          <p>Verify the permanent ID, configured AMS slot, state transition, and effective time.</p></div>
        <section class="replacement-timeline initialization-preview"
          aria-label="Verified AMS initialization preview">
          <article><span class="step-number">1</span><div><p>Identified spool</p>
            <h2>{esc(spool["permanent_id"])}</h2>
            <span>{esc(spool["manufacturer"])} · {esc(spool["product_line"])} ·
              {esc(spool["color"])}</span><small>Current state: {esc(spool["state"].title())}</small>
          </div></article>
          <span class="timeline-arrow" aria-hidden="true">↓</span>
          <article><span class="step-number">2</span><div><p>Controlled transition</p>
            <h2>{esc(transition)}</h2><span>No spool weight change</span></div></article>
          <span class="timeline-arrow" aria-hidden="true">↓</span>
          <article><span class="step-number">3</span><div><p>Verified destination</p>
            <h2>{esc(slot["equipment_name"])} Slot {slot["slot_number"]}</h2>
            <span>Effective {esc(v["effective_local"])}</span></div></article>
        </section>
        <section class="panel review-panel"><h2>Audit context</h2><dl class="detail-list">
          <div><dt>Actor</dt><dd>{esc(v["actor"])}</dd></div>
          <div><dt>Module</dt><dd>{esc(v["module"])}</dd></div>
          <div><dt>Effective timestamp</dt><dd>{esc(v["effective_at"])}</dd></div>
          <div><dt>Reason</dt><dd>{display(v["reason"], "No reason provided")}</dd></div>
        </dl></section>
        <form class="confirm-form" method="post"
          action="/inventory/filament/ams/initialize/confirm">
          <input type="hidden" name="review_token" value="{esc(review.token)}">
          <label class="choice confirm-choice"><input type="checkbox" name="confirm"
            value="initialize" required><span><strong>Initialize this exact verified assignment.</strong>
            <small>The operation succeeds completely or saves nothing.</small></span></label>
          <div class="form-actions"><a href="/inventory/filament/ams/initialize">
            Go back without saving</a><button type="submit">Confirm verified AMS state</button></div>
        </form>"""
        return self._shell(
            "Preview Verified AMS State", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<a href="/inventory/filament/ams">AMS Units</a> / '
            '<span aria-current="page">Preview initialization</span>',
        )

    def _initialization_complete(self, result: dict) -> str:
        spool, slot, assignment = result["spool"], result["slot"], result["assignment"]
        open_record = (
            f'#{result["open_action_id"]}' if result["open_action_id"] else "Not required — already Open"
        )
        content = f"""
        <div class="success-panel"><p class="eyebrow">Verified AMS state initialized</p>
          <h2>{esc(spool["permanent_id"])} is loaded</h2>
          <p>{esc(slot["equipment_name"])} Slot {slot["slot_number"]} now matches the verified
          physical state.</p></div>
        <div class="detail-grid">
          <section class="panel"><h2>Physical assignment</h2><dl class="detail-list">
            <div><dt>Spool</dt><dd>{esc(spool["permanent_id"])}</dd></div>
            <div><dt>AMS destination</dt><dd>{esc(slot["equipment_name"])}
              Slot {slot["slot_number"]}</dd></div>
            <div><dt>Effective timestamp</dt><dd>{esc(assignment["loaded_at"])}</dd></div>
            <div><dt>Weight changed</dt><dd>No</dd></div>
          </dl></section>
          <section class="panel"><h2>Immutable history</h2><dl class="detail-list">
            <div><dt>Open action</dt><dd>{open_record}</dd></div>
            <div><dt>Load action</dt><dd>#{result["load_action_id"]}</dd></div>
            <div><dt>Load transaction</dt><dd>#{assignment["load_transaction_id"]}</dd></div>
            <div><dt>AMS assignment</dt><dd>#{assignment["id"]}</dd></div>
          </dl></section>
        </div>
        <div class="form-actions"><a href="/inventory/filament/ams/initialize">
          Initialize another verified slot</a>
          <a class="primary-link" href="/inventory/filament/ams">View AMS Units</a></div>"""
        return self._shell(
            "Verified AMS Initialization Complete", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">Initialization complete</span>',
        )

    def _initialization_error(self, message: str) -> str:
        content = f"""<section class="empty-state"><p class="eyebrow">No changes saved</p>
          <h2>AMS initialization stopped</h2><p>{esc(message)}</p>
          <a class="primary-link" href="/inventory/filament/ams/initialize">
            Start a fresh verified initialization</a></section>"""
        return self._shell(
            "AMS initialization stopped", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament/ams">AMS Units</a> / '
            '<span aria-current="page">Initialization stopped</span>',
        )

    def _return_spool_form(self) -> str:
        options = self.returning.options()
        spools = "".join(
            f'<option value="{spool["id"]}">{esc(spool["permanent_id"])} — '
            f'{esc(spool["manufacturer"])} {esc(spool["color"])} — '
            f'{esc(spool["equipment_name"])} Slot {spool["slot_number"]}</option>'
            for spool in options["spools"]
        )
        locations = "".join(
            f'<option value="{location["id"]}">{esc(location["name"])}</option>'
            for location in options["locations"]
        )
        empty = (
            '<div class="notice"><strong>No loaded spools are available</strong>'
            '<p>Initialize or load a verified spool before using this workflow.</p></div>'
            if not options["spools"] else ""
        )
        content = f"""{empty}
        <div class="notice"><strong>Controlled AMS unload</strong>
          <p>Use this only after physically removing the selected spool and placing it
          in the selected storage location. Remaining weight is preserved.</p></div>
        <form class="receive-form" method="post"
          action="/inventory/filament/ams/return/review">
          <fieldset><legend>Verified spool return</legend><div class="form-grid">
            <label class="wide-field"><span>Currently loaded spool</span>
              <select name="instance_id" required><option value="">Select loaded spool</option>
              {spools}</select></label>
            <label><span>Storage destination</span><select name="destination_location_id"
              required><option value="">Select destination</option>{locations}</select></label>
            <label><span>Actor</span><input name="actor" value="Cowboy"
              maxlength="100" required></label>
            <label class="wide-field"><span>Reason (optional)</span>
              <input name="reason" maxlength="500"
                value="Verified physical return from AMS to storage"></label>
          </div>
          <label class="choice"><input type="checkbox" name="physically_verified"
            value="yes" required><span><strong>I physically verified the spool,
            AMS slot, and storage destination.</strong><small>No inventory record
            changes until the confirmation step.</small></span></label></fieldset>
          <div class="form-actions"><a href="/">Cancel</a>
            <button type="submit">Preview return to storage</button></div>
        </form>"""
        return self._shell(
            "Return AMS Spool to Storage", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament/ams">AMS Units</a> / '
            '<span aria-current="page">Return spool to storage</span>',
            description="Unload one verified active spool without changing its remaining weight.",
        )

    def _return_spool_review(self, review) -> str:
        spool = review.values["spool"]
        destination = review.values["destination"]
        content = f"""
        <div class="notice"><strong>Preview only — zero writes</strong>
          <p>Confirm the exact spool, AMS source, and physical storage destination.</p></div>
        <section class="replacement-timeline return-preview"
          aria-label="Return AMS spool to storage preview">
          <article><span class="step-number">1</span><div><p>Unload from AMS</p>
            <h2>{esc(spool["permanent_id"])}</h2>
            <span>{esc(spool["equipment_name"])} Slot {spool["slot_number"]}</span>
            <small>{esc(spool["manufacturer"])} · {esc(spool["color"])}</small>
          </div></article>
          <span class="timeline-arrow" aria-hidden="true">→</span>
          <article><span class="step-number">2</span><div><p>Place in verified storage</p>
            <h2>{esc(destination["name"])}</h2>
            <span>State becomes Open</span>
            <small>Remaining weight stays {grams(spool["remaining_quantity"])}</small>
          </div></article>
        </section>
        <form class="confirm-form" method="post"
          action="/inventory/filament/ams/return/confirm">
          <input type="hidden" name="review_token" value="{esc(review.token)}">
          <label class="choice confirm-choice"><input type="checkbox" name="confirm"
            value="return-spool" required><span><strong>Record this exact verified
            return.</strong><small>The unload, move, transaction, and audit succeed
            together or nothing is saved.</small></span></label>
          <div class="form-actions"><a href="/inventory/filament/ams/return">
            Go back without saving</a><button type="submit">Confirm return to storage</button></div>
        </form>"""
        return self._shell(
            "Preview Return to Storage", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament/ams/return">'
            'Return spool</a> / <span aria-current="page">Preview</span>',
        )

    def _return_spool_complete(self, result: dict) -> str:
        spool = result["spool"]
        destination = result["destination"]
        content = f"""
        <div class="success-panel"><p class="eyebrow">Verified return completed</p>
          <h2>{esc(spool["permanent_id"])} is now in {esc(destination["name"])}</h2>
          <p>The AMS slot is available and the spool remains Open with
          {grams(result["remaining_quantity"])} recorded.</p></div>
        <section class="panel"><h2>Immutable history</h2><dl class="detail-list">
          <div><dt>Action</dt><dd>#{result["action_id"]}</dd></div>
          <div><dt>Transaction</dt><dd>#{result["transaction_id"]}</dd></div>
          <div><dt>Actor</dt><dd>{esc(result["actor"])}</dd></div>
          <div><dt>Weight changed</dt><dd>No</dd></div>
        </dl></section>
        <div class="form-actions"><a href="/inventory/filament/ams/return">
          Return another spool</a>
          <a class="primary-link" href="/inventory/filament/ams">View AMS Units</a></div>"""
        return self._shell(
            "Return to Storage Complete", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament/ams">AMS Units</a> / '
            '<span aria-current="page">Return completed</span>',
        )

    def _return_spool_error(self, message: str) -> str:
        content = f"""<section class="empty-state"><p class="eyebrow">No changes saved</p>
          <h2>Spool return stopped</h2><p>{esc(message)}</p>
          <a class="primary-link" href="/inventory/filament/ams/return">
            Start a fresh verified return</a></section>"""
        return self._shell(
            "Spool return stopped", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament/ams">AMS Units</a> / '
            '<span aria-current="page">Return stopped</span>',
        )

    def _method_not_allowed(self) -> str:
        return self._error_page(
            "Method not allowed", "This route does not accept that type of request.", status="405"
        )

    def _product(self, p: dict) -> str:
        rule = (
            f'<span class="status {"warning" if p["remaining_grams"] < p["stock_rule"]["minimum_quantity"] else "good"}">'
            f'Minimum {grams(p["stock_rule"]["minimum_quantity"])}</span>'
            if p["stock_rule"]
            else '<span class="status neutral">No reorder rule set</span>'
        )
        spools = []
        for s in p["spools"]:
            available = max(0, s["remaining_quantity"] - s["reserved_grams"])
            spools.append(f"""
            <tr><td data-label="Spool"><a href="/inventory/filament/spools/{s["id"]}">{esc(s["permanent_id"])}</a></td>
              <td data-label="Status"><span class="status {esc(s["state"])}">{esc(s["state"].title())}</span></td>
              <td data-label="Location">{display(s["location_name"])}</td>
              <td data-label="Original">{grams(s["original_quantity"])}</td>
              <td data-label="Remaining">{grams(s["remaining_quantity"])}</td>
              <td data-label="Reserved">{grams(s["reserved_grams"])}</td>
              <td data-label="Available">{grams(available)}</td>
              <td data-label="Opened">{display(s["opened_at"])}</td>
              <td data-label="Archived">{display(s["archived_at"])}</td></tr>""")
        note = f'<div class="notice"><strong>Use-up stock</strong><p>{esc(p["notes"])}</p></div>' if p["use_up_stock"] else (
            f'<div class="notice subdued"><strong>Product notes</strong><p>{esc(p["notes"])}</p></div>' if p["notes"] else ""
        )
        content = f"""
        {note}
        <div class="detail-grid">
          <section class="panel"><h2>Product specifications</h2><dl class="detail-list">
            <div><dt>Manufacturer</dt><dd>{esc(p["manufacturer"])}</dd></div>
            <div><dt>Product line</dt><dd>{esc(p["product_line"])}</dd></div>
            <div><dt>Material</dt><dd>{display(p["material"])}</dd></div>
            <div><dt>Manufacturer color</dt><dd>{display(p["color"])}</dd></div>
            <div><dt>Color code</dt><dd>{display(p["color_code"])}</dd></div>
            <div><dt>Diameter</dt><dd>{esc(p["diameter_mm"])} mm</dd></div>
            <div><dt>Nominal spool weight</dt><dd>{grams(p["nominal_weight_g"])}</dd></div>
          </dl></section>
          <section class="panel"><h2>Grouped totals</h2><dl class="detail-list">
            <div><dt>Physical spools</dt><dd>{p["physical_spools"]}</dd></div>
            <div><dt>Nominal total</dt><dd>{grams(p["nominal_total_grams"])}</dd></div>
            <div><dt>Estimated remaining</dt><dd>{grams(p["remaining_grams"])}</dd></div>
            <div><dt>Reserved</dt><dd>{grams(p["reserved_grams"])}</dd></div>
            <div><dt>Available</dt><dd>{grams(p["available_grams"])}</dd></div>
            <div><dt>Reorder status</dt><dd>{rule}</dd></div>
          </dl></section>
        </div>
        <section><div class="section-heading"><div><h2>Physical spools</h2>
          <p>Individual records behind this grouped product.</p></div></div>
          <div class="table-wrap"><table><thead><tr><th>Spool</th><th>Status</th><th>Location</th>
          <th>Original</th><th>Remaining</th><th>Reserved</th><th>Available</th>
          <th>Opened</th><th>Archived</th></tr></thead><tbody>{''.join(spools)}</tbody></table></div>
        </section>"""
        return self._shell(
            f'{p["product_line"]} — {p["color"]}', content,
            f'<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            f'<span aria-current="page">{esc(p["manufacturer"])} {esc(p["color"])}</span>',
        )

    def _spool(self, s: dict) -> str:
        legacy_remaining = (
            "Unknown"
            if s.get("quantity_mode") == "unknown"
            else (
                f'{grams(s["registered_remaining_quantity"])} '
                f'({s["quantity_mode"]})'
                if s.get("quantity_mode") else grams(s["remaining_quantity"])
            )
        )
        legacy_confidence = (
            s["quantity_confidence"].replace("_", " ").title()
            if s.get("quantity_confidence") else None
        )
        transactions = (
            "".join(
                f'<tr><td data-label="When">{esc(t["occurred_at"])}</td>'
                f'<td data-label="Action">{esc(t["transaction_type"].replace("_"," ").title())}</td>'
                f'<td data-label="Change">{esc(t["quantity_change"])} {esc(t["unit"])}</td>'
                f'<td data-label="Movement">{display(t["source_location"],"—")} → '
                f'{display(t["destination_location"],"—")}</td>'
                f'<td data-label="Reason">{display(t["reason"],"No reason recorded")}</td></tr>'
                for t in s["transactions"]
            )
            if s["transactions"]
            else '<tr><td colspan="5"><div class="empty-inline">No transaction history recorded for this seeded spool.</div></td></tr>'
        )
        content = f"""
        <div class="detail-grid">
          <section class="panel"><h2>Spool identity</h2><dl class="detail-list">
            <div><dt>Permanent ID</dt><dd><strong>{esc(s["permanent_id"])}</strong></dd></div>
            <div><dt>Manufacturer</dt><dd>{esc(s["manufacturer"])}</dd></div>
            <div><dt>Product line</dt><dd>{esc(s["product_line"])}</dd></div>
            <div><dt>Material</dt><dd>{display(s["material"])}</dd></div>
            <div><dt>Color</dt><dd>{esc(s["color"])}</dd></div>
            <div><dt>Diameter</dt><dd>{esc(s["diameter_mm"])} mm</dd></div>
            <div><dt>Tracking override</dt><dd>{"Yes — exceptional record" if s["tracking_policy_override"] else "No"}</dd></div>
          </dl></section>
          <section class="panel"><h2>Current inventory state</h2><dl class="detail-list">
            <div><dt>State</dt><dd><span class="status {esc(s["state"])}">{esc(s["state"].title())}</span></dd></div>
            <div><dt>Location</dt><dd>{display(s["location_name"])}</dd></div>
            <div><dt>Original filament</dt><dd>{grams(s["original_quantity"])}</dd></div>
            <div><dt>Remaining quantity</dt><dd>{esc(legacy_remaining)}</dd></div>
            <div><dt>Quantity confidence</dt><dd>{display(legacy_confidence)}</dd></div>
            <div><dt>Reserved</dt><dd>{grams(s["reserved_grams"])}</dd></div>
            <div><dt>Available</dt><dd>{grams(s["available_grams"])}</dd></div>
          </dl></section>
          <section class="panel"><h2>Dates and notes</h2><dl class="detail-list">
            <div><dt>Purchase date</dt><dd>{display(s["purchase_date"])}</dd></div>
            <div><dt>Opened</dt><dd>{display(s["opened_at"])}</dd></div>
            <div><dt>Emptied</dt><dd>{display(s["emptied_at"])}</dd></div>
            <div><dt>Archived</dt><dd>{display(s["archived_at"])}</dd></div>
            <div><dt>Created</dt><dd>{display(s["created_at"])}</dd></div>
            <div><dt>Updated</dt><dd>{display(s["updated_at"])}</dd></div>
            <div><dt>Notes</dt><dd>{display(s["notes"])}</dd></div>
            <div><dt>Legacy registration note</dt><dd>{display(s.get("registration_note"))}</dd></div>
          </dl></section>
        </div>
        <section><div class="section-heading"><div><h2>Transaction history</h2>
          <p>Read-only audit trail, newest first.</p></div></div>
          <div class="table-wrap"><table><thead><tr><th>When</th><th>Action</th>
          <th>Quantity change</th><th>Movement</th><th>Reason</th></tr></thead>
          <tbody>{transactions}</tbody></table></div></section>"""
        return self._shell(
            s["permanent_id"], content,
            f'<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            f'<a href="/inventory/filament/products/{s["catalog_item_id"]}">{esc(s["color"])}</a> / '
            f'<span aria-current="page">{esc(s["permanent_id"])}</span>',
        )

    def _orders(self) -> str:
        rows = []
        for order in self.queries.orders():
            remaining = max(0, order["expected_quantity"] - order["received_quantity"])
            action = (
                f'<a class="primary-link" href="/orders/{order["id"]}/receive">Review receipt</a>'
                if order["state"] in {"ordered", "shipped", "delivered"} else ""
            )
            rows.append(f"""<article class="order-card"><div class="product-title"><div>
              <p class="eyebrow">{esc(order["order_number"])}</p><h2>{esc(order["description"])}</h2>
              <p>{esc(order["supplier"])} · {esc(order["material"])} ·
              <i class="color-swatch" style="--swatch:{self._swatch(order["color"])}"></i>{esc(order["color"])}</p>
              </div><span class="status neutral">{esc(order["state"].title())}</span></div>
              <dl class="compact-stats"><div><dt>Expected</dt><dd>{order["expected_quantity"]} {esc(order["unit_label"])}</dd></div>
              <div><dt>Received</dt><dd>{order["received_quantity"]}</dd></div>
              <div><dt>Remaining</dt><dd>{remaining}</dd></div>
              <div><dt>Inventory impact</dt><dd>{"Recorded" if order["received_quantity"] else "None yet"}</dd></div></dl>
              <p>{esc(order["notes"] or "")}</p>{action}</article>""")
        return self._shell(
            "Orders", f'<section class="order-list">{"".join(rows)}</section>',
            '<a href="/">Dashboard</a> / <span aria-current="page">Orders</span>',
            description="Incoming stock stays separate from physical inventory until verified receipt.",
        )

    def _order_receipt_form(self, order_id: int) -> str:
        order = self.queries.order_detail(order_id)
        if not order or order["state"] not in {"ordered", "shipped", "delivered"}:
            return self._not_found()
        options = self.order_receiving.options()
        locations = "".join(
            f'<option value="{loc["id"]}">{esc(loc["name"])}</option>'
            for loc in options["locations"]
        )
        content = f"""<div class="notice"><strong>Controlled order receipt</strong>
          <p>Expected quantity is not inventory. Enter only the count and condition physically verified after arrival.</p></div>
        <section class="panel"><h2>{esc(order["order_number"])} · {esc(order["description"])}</h2>
          <p>{esc(order["supplier"])} · Expected {order["expected_quantity"]} {esc(order["unit_label"])}
          · Received so far {order["received_quantity"]}</p></section>
        <form class="receive-form" method="post" action="/orders/receive/review">
          <input type="hidden" name="order_id" value="{order_id}">
          <fieldset><legend>Verified delivery</legend><div class="form-grid">
            <label><span>Actual accepted refill rolls</span><input type="number" name="actual_quantity"
              min="1" max="100" required></label>
            <label><span>Condition</span><select name="condition" required>
              <option value="new">New</option><option value="good">Good</option>
              <option value="damaged">Damaged</option></select></label>
            <label><span>Receiving location</span><select name="location_id" required>{locations}</select></label>
            <label><span>Actor</span><input name="actor" value="Cowboy" maxlength="100" required></label>
            <label class="wide-field"><span>Reason (optional)</span>
              <input name="reason" maxlength="500" value="Verified Overture shipment receipt"></label>
            <label class="wide-field"><span>Condition or delivery note (optional)</span>
              <textarea name="note" maxlength="500"></textarea></label></div>
            <label class="choice"><input type="checkbox" name="physically_verified" value="yes" required>
              <span><strong>I physically verified the delivered quantity and condition.</strong>
              <small>No physical inventory is created until the confirmation step.</small></span></label>
          </fieldset><div class="form-actions"><a href="/orders">Cancel</a>
            <button type="submit">Preview order receipt</button></div></form>"""
        return self._shell(
            "Receive Verified Order", content,
            '<a href="/">Dashboard</a> / <a href="/orders">Orders</a> / '
            '<span aria-current="page">Review delivery</span>',
        )

    def _order_receipt_review(self, review) -> str:
        v, order = review.values, review.values["order"]
        ids = "".join(f"<li>{esc(value)}</li>" for value in v["permanent_ids"])
        content = f"""<div class="notice"><strong>Preview only · zero writes</strong>
          <p>Confirm the exact received quantity, product identity, condition, location, and permanent IDs.</p></div>
        <section class="panel review-panel"><h2>{esc(order["order_number"])} receipt preview</h2>
          <dl class="detail-list"><div><dt>Actual manufacturer</dt><dd>{esc(order["manufacturer"])}</dd></div>
          <div><dt>Product</dt><dd>{esc(order["product_line"])} · {esc(order["variant"])}</dd></div>
          <div><dt>Verified quantity</dt><dd>{v["actual_quantity"]} refill rolls</dd></div>
          <div><dt>Condition</dt><dd>{esc(v["condition"].title())}</dd></div>
          <div><dt>Location</dt><dd>{esc(v["location"])}</dd></div>
          <div><dt>Actor</dt><dd>{esc(v["actor"])}</dd></div></dl>
          <h3>Permanent THS-FIL IDs to create</h3><ul class="id-preview">{ids}</ul></section>
        <form class="confirm-form" method="post" action="/orders/receive/confirm">
          <input type="hidden" name="review_token" value="{esc(review.token)}">
          <label class="choice"><input type="checkbox" name="confirm" value="receive-order" required>
            <span><strong>Receive this exact verified shipment.</strong>
            <small>The batch and all physical instances succeed together or nothing is saved.</small></span></label>
          <div class="form-actions"><a href="/orders/{order["id"]}/receive">Go back without saving</a>
            <button type="submit">Confirm atomic receipt</button></div></form>"""
        return self._shell(
            "Preview Order Receipt", content,
            '<a href="/">Dashboard</a> / <a href="/orders">Orders</a> / '
            '<span aria-current="page">Preview receipt</span>',
        )

    def _order_receipt_complete(self, result: dict) -> str:
        ids = "".join(f"<li>{esc(value)}</li>" for value in result["permanent_ids"])
        content = f"""<div class="success-panel"><p class="eyebrow">Atomic receipt completed</p>
          <h2>{result["actual_quantity"]} Overture refill roll(s) received</h2>
          <p>Receiving batch {esc(result["batch_uuid"])} links every new physical instance to
          {esc(result["order_number"])}.</p></div>
          <section class="panel"><h2>Created physical inventory</h2><ul class="id-preview">{ids}</ul>
          <dl class="detail-list"><div><dt>Actual manufacturer</dt><dd>{esc(result["manufacturer"])}</dd></div>
          <div><dt>Order state</dt><dd>{esc(result["state"].title())}</dd></div>
          <div><dt>Still expected</dt><dd>{result["remaining_quantity"]}</dd></div></dl></section>
          <div class="form-actions"><a href="/orders">View Orders</a>
          <a class="primary-link" href="/inventory/filament">View filament inventory</a></div>"""
        return self._shell(
            "Order Received", content,
            '<a href="/">Dashboard</a> / <a href="/orders">Orders</a> / '
            '<span aria-current="page">Receipt completed</span>',
        )

    def _order_receipt_error(self, message: str) -> str:
        return self._shell(
            "Order receipt stopped",
            f'<section class="empty-state"><p class="eyebrow">Nothing received</p>'
            f'<h2>Order receipt stopped</h2><p>{esc(message)}</p>'
            f'<a class="primary-link" href="/orders">Return to Orders</a></section>',
            '<a href="/">Dashboard</a> / <a href="/orders">Orders</a> / '
            '<span aria-current="page">Receipt stopped</span>',
        )

    def _ams(self) -> str:
        units = []
        for unit in self.queries.ams_status():
            slots = []
            for slot in unit["slots"]:
                if slot["assignment_id"]:
                    remaining = (
                        "Unknown remaining"
                        if slot.get("quantity_mode") == "unknown"
                        else f'{grams(slot["registered_remaining_quantity"])} remaining'
                        if slot.get("quantity_mode")
                        else f'{grams(slot["remaining_quantity"])} remaining'
                    )
                    status = f"""<a href="/inventory/filament/spools/{slot["spool_id"]}">
                      <strong>{esc(slot["permanent_id"])}</strong></a>
                      <span>{esc(slot["manufacturer"])} · {esc(slot["material"])} · {esc(slot["color"])}</span>
                      <span>{esc(remaining)}</span>"""
                else:
                    status = '<strong>Empty</strong><span>No verified spool assignment</span>'
                slots.append(f'<li class="ams-slot"><span class="slot-number">Slot {slot["slot_number"]}</span>'
                             f'<div>{status}</div></li>')
            units.append(f'<article class="ams-unit"><div class="product-title"><div><p class="eyebrow">Equipment</p>'
                         f'<h2>{esc(unit["name"])}</h2></div><span class="status neutral">Read only</span></div>'
                         f'<ol>{''.join(slots)}</ol></article>')
        content = f"""<div class="notice"><strong>Verified assignments only</strong>
          <p>AMS slots show only committed physical assignments. Historical assumptions were not imported.</p>
          <p><a class="primary-link" href="/inventory/filament/ams/initialize">
            Initialize one verified AMS slot</a></p></div>
          <section class="ams-grid">{"".join(units)}</section>"""
        return self._shell(
            "AMS Units", content,
            '<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            '<span aria-current="page">AMS Units</span>',
            description="Live equipment and slot records from SQLite.",
        )

    def _placeholder(self, name: str) -> str:
        content = f"""<section class="empty-state coming-soon"><p class="eyebrow">Planned module</p>
          <h2>Coming Soon</h2><p>{esc(name)} is part of the broader THS Inventory System roadmap.
          It is shown here so future trades and workshop profiles can enable it without redesigning navigation.</p>
          <a class="primary-link" href="/">Return to dashboard</a></section>"""
        return self._shell(
            name, content,
            f'<a href="/">Dashboard</a> / <span aria-current="page">{esc(name)}</span>',
            description="This module is not active in the read-only dashboard checkpoint.",
        )

    def _not_found(self) -> str:
        return self._error_page(
            "Page not found",
            "That product, spool, or module does not exist in the current inventory.",
            status="404",
        )

    def _database_error(self, message: str) -> str:
        return self._error_page(
            "Inventory database is not ready",
            message,
            status="Startup check",
        )

    def _error_page(self, title: str, message: str, *, status="Error") -> str:
        content = f"""<section class="empty-state"><p class="eyebrow">{esc(status)}</p>
          <h2>{esc(title)}</h2><p>{esc(message)}</p><a class="primary-link" href="/">Return home</a></section>"""
        return self._shell(title, content, f'<span aria-current="page">{esc(title)}</span>')

    def _static(self, path: str) -> tuple[int, list[tuple[str, str]], bytes]:
        name = path.removeprefix("/static/")
        if "/" in name or "\\" in name or name not in {"style.css", "app.js"}:
            return 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found"
        file = STATIC / name
        if not file.is_file():
            return 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found"
        content = file.read_bytes()
        return 200, [
            ("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream"),
            ("Content-Length", str(len(content))),
            ("Cache-Control", "public, max-age=300"),
        ], content


def make_handler(app: InventoryWebApp):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = app.response(self.path)
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            status, headers, _ = app.response(self.path)
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()

        def do_POST(self):
            content_type = self.headers.get("Content-Type", "")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if content_type.split(";", 1)[0].strip() != "application/x-www-form-urlencoded":
                self.send_error(415, "Form submissions only")
                return
            if length < 0 or length > 32768:
                self.send_error(413, "Form submission is too large")
                return
            raw = self.rfile.read(length).decode("utf-8")
            parsed = parse_qs(raw, keep_blank_values=True)
            form = {key: values[-1] for key, values in parsed.items()}
            status, headers, body = app.response(self.path, method="POST", form=form)
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            print(f"[THS Inventory] {self.address_string()} - {format % args}")

    return Handler


def create_server(database=DEFAULT_DB, host="127.0.0.1", port=8787) -> ThreadingHTTPServer:
    app = InventoryWebApp(database)
    return ThreadingHTTPServer((host, port), make_handler(app))


def serve(database=DEFAULT_DB, host="127.0.0.1", port=8787) -> None:
    app = InventoryWebApp(database)
    with closing(app.queries.connect()):
        pass
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"THS Inventory System running at http://{host}:{port}")
    print("Controlled inventory workflows enabled. General editing remains unavailable. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTHS Inventory System stopped.")
    finally:
        server.server_close()
