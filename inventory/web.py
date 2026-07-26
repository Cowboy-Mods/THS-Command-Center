from __future__ import annotations

import html
import mimetypes
import re
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .db import DEFAULT_DB, ROOT
from .navigation import MODULES, NAVIGATION
from .queries import DatabaseNotReady, InventoryQueries

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

    def response(self, target: str) -> tuple[int, list[tuple[str, str]], bytes]:
        url = urlsplit(target)
        if url.path.startswith("/static/"):
            return self._static(url.path)
        try:
            body, status = self._route(url.path, parse_qs(url.query))
        except DatabaseNotReady as exc:
            body, status = self._database_error(str(exc)), 503
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

    def _route(self, path: str, query: dict[str, list[str]]) -> tuple[str, int]:
        if path == "/":
            return self._dashboard(), 200
        if path == "/inventory/filament":
            return self._filament_inventory(query), 200
        if path == "/inventory/filament/ams":
            return self._ams(), 200
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
  <title>{esc(title)} Â· THS Inventory System</title>
  <link rel="stylesheet" href="/static/style.css?v=1">
  <script src="/static/app.js?v=1" defer></script>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <header class="topbar">
    <button class="nav-toggle" type="button" aria-controls="site-navigation"
      aria-expanded="false"><span aria-hidden="true">â˜°</span><span>Menu</span></button>
    <a class="brand" href="/"><span class="brand-mark">THS</span>
      <span><strong>Inventory System</strong><small>THS Command Center</small></span></a>
    <span class="readonly-badge">Read-only checkpoint</span>
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
                <h2><a href="/inventory/filament/products/{p["id"]}">{esc(p["product_line"])} â€” {esc(p["color"])}</a></h2>
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
          <span>One card per catalog product</span></div>
        <section class="product-grid" aria-label="Grouped filament products">{result}</section>"""
        return self._shell(
            "Filament Inventory", content,
            '<a href="/">Dashboard</a> / <span aria-current="page">Filament Inventory</span>',
            description="Grouped by manufacturer, product line, and color. Select a product to inspect its physical spools.",
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
            f'{p["product_line"]} â€” {p["color"]}', content,
            f'<a href="/">Dashboard</a> / <a href="/inventory/filament">Filament</a> / '
            f'<span aria-current="page">{esc(p["manufacturer"])} {esc(p["color"])}</span>',
        )

    def _spool(self, s: dict) -> str:
        transactions = (
            "".join(
                f'<tr><td data-label="When">{esc(t["occurred_at"])}</td>'
                f'<td data-label="Action">{esc(t["transaction_type"].replace("_"," ").title())}</td>'
                f'<td data-label="Change">{esc(t["quantity_change"])} {esc(t["unit"])}</td>'
                f'<td data-label="Movement">{display(t["source_location"],"â€”")} â†’ '
                f'{display(t["destination_location"],"â€”")}</td>'
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
            <div><dt>Tracking override</dt><dd>{"Yes â€” exceptional record" if s["tracking_policy_override"] else "No"}</dd></div>
          </dl></section>
          <section class="panel"><h2>Current inventory state</h2><dl class="detail-list">
            <div><dt>State</dt><dd><span class="status {esc(s["state"])}">{esc(s["state"].title())}</span></dd></div>
            <div><dt>Location</dt><dd>{display(s["location_name"])}</dd></div>
            <div><dt>Original filament</dt><dd>{grams(s["original_quantity"])}</dd></div>
            <div><dt>Estimated remaining</dt><dd>{grams(s["remaining_quantity"])}</dd></div>
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

    def _ams(self) -> str:
        units = []
        for unit in self.queries.ams_status():
            slots = []
            for slot in unit["slots"]:
                if slot["assignment_id"]:
                    status = f"""<a href="/inventory/filament/spools/{slot["spool_id"]}">
                      <strong>{esc(slot["permanent_id"])}</strong></a>
                      <span>{esc(slot["manufacturer"])} Â· {esc(slot["material"])} Â· {esc(slot["color"])}</span>
                      <span>{grams(slot["remaining_quantity"])} remaining</span>"""
                else:
                    status = '<strong>Empty</strong><span>No verified spool assignment</span>'
                slots.append(f'<li class="ams-slot"><span class="slot-number">Slot {slot["slot_number"]}</span>'
                             f'<div>{status}</div></li>')
            units.append(f'<article class="ams-unit"><div class="product-title"><div><p class="eyebrow">Equipment</p>'
                         f'<h2>{esc(unit["name"])}</h2></div><span class="status neutral">Read only</span></div>'
                         f'<ol>{''.join(slots)}</ol></article>')
        content = f'<div class="notice"><strong>Verified assignments only</strong><p>All current slots are empty. Stale assumptions were not imported.</p></div><section class="ams-grid">{"".join(units)}</section>'
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
    print("Read-only checkpoint. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTHS Inventory System stopped.")
    finally:
        server.server_close()

