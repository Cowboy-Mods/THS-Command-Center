from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from .actions import ActionContext, InventoryActionService


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "verified"}


def import_csv(
    db: sqlite3.Connection, path: Path, *, apply: bool = False, allow_unverified: bool = False
) -> dict:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = db.execute(
        "SELECT id,status FROM import_batches WHERE content_hash=?", (digest,)
    ).fetchone()
    if existing and existing["status"] == "applied" and apply:
        return {"batch_id": existing["id"], "accepted": 0, "rejected": 0, "warnings": 1}
    batch_id = db.execute(
        "INSERT INTO import_batches(filename,content_hash,status,dry_run) VALUES (?,?,?,?)",
        (path.name, digest, "validating", int(not apply)),
    ).lastrowid
    accepted = rejected = warnings = 0
    audit_rows: list[tuple[int, str | None, str, str | None, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    actions = InventoryActionService(
        db,
        ActionContext(actor=f"importer:{path.name}", module="inventory-import", origin="importer"),
    )
    try:
        db.execute("SAVEPOINT inventory_import")
        for number, row in enumerate(rows, 2):
            errors: list[str] = []
            if not _truthy(row.get("verified_status", "")) and not allow_unverified:
                errors.append("row is not verified")
            tracking = row.get("tracking_method", "")
            if tracking not in {"quantity", "individual", "lot"}:
                errors.append("invalid tracking_method")
            configured_type = db.execute(
                "SELECT id,tracking_method FROM item_types WHERE name=?", (row.get("item_type"),)
            ).fetchone()
            if configured_type and configured_type["tracking_method"] != tracking:
                errors.append(
                    f"tracking policy conflicts with configured item type "
                    f"({configured_type['tracking_method']})"
                )
            try:
                quantity = float(row.get("quantity") or 0)
                count = int(row.get("instance_count") or 0)
                remaining = float(row.get("remaining_quantity") or quantity)
                if min(quantity, count, remaining) < 0:
                    errors.append("quantities cannot be negative")
                if tracking == "individual" and count < 1:
                    errors.append("individual tracking requires instance_count of at least 1")
                if tracking in {"quantity", "lot"} and count != 0:
                    errors.append(f"{tracking} tracking cannot create individual instances")
                if remaining > quantity:
                    errors.append("remaining quantity cannot exceed starting quantity")
            except ValueError:
                errors.append("invalid numeric value")
                quantity = remaining = 0
                count = 0
            unit = db.execute("SELECT id FROM units WHERE code=?", (row.get("unit"),)).fetchone()
            if not unit:
                errors.append("unknown unit")
            location = db.execute(
                "SELECT id FROM locations WHERE name=?", (row.get("location"),)
            ).fetchone()
            if not location:
                errors.append("unknown location")
            external_id = row.get("external_id", "").strip()
            if external_id and db.execute(
                "SELECT 1 FROM import_rows WHERE external_id=? AND status='accepted'",
                (external_id,),
            ).fetchone():
                errors.append("duplicate external_id")
            if errors:
                rejected += 1
                audit_rows.append(
                    (number, external_id or None, "rejected", "; ".join(errors), json.dumps(row))
                )
                continue
            accepted += 1
            audit_rows.append(
                (number, external_id or None, "accepted" if apply else "validated", None, json.dumps(row))
            )
            if apply:
                category_id = actions.ensure_category(row["category"])
                item_type_id = actions.ensure_item_type(
                    category_id, row["item_type"], tracking, unit["id"]
                )
                maker_id = actions.ensure_manufacturer(row["manufacturer"])
                product_id, created = actions.ensure_catalog_item(
                    item_type_id,
                    maker_id,
                    row["product_name"],
                    row.get("product_line", ""),
                    row.get("variant", ""),
                    unit["id"],
                    row.get("notes"),
                )
                if not created:
                    warnings += 1
                action_reason = f"Import batch {batch_id}, row {number}"
                if tracking == "individual":
                    for _ in range(count):
                        actions.add_individual_instance(
                            product_id,
                            state=row.get("state") or "sealed",
                            location_id=location["id"],
                            original_quantity=quantity,
                            remaining_quantity=remaining,
                            unit_id=unit["id"],
                            lot_number=row.get("lot_number") or None,
                            condition=row.get("condition") or "new",
                            expires_at=row.get("expiration_date") or None,
                            notes=row.get("notes") or None,
                            verified=True,
                            reason=action_reason,
                        )
                else:
                    actions.add_stock_lot(
                        product_id,
                        location_id=location["id"],
                        lot_number=row.get("lot_number") or None,
                        quantity=quantity,
                        unit_id=unit["id"],
                        condition=row.get("condition") or "new",
                        expires_at=row.get("expiration_date") or None,
                        verified=True,
                        reason=action_reason,
                    )
        if rejected:
            db.execute("ROLLBACK TO inventory_import")
            db.execute("RELEASE inventory_import")
            status = "rejected"
        elif not apply:
            db.execute("ROLLBACK TO inventory_import")
            db.execute("RELEASE inventory_import")
            status = "validated"
        else:
            db.execute("RELEASE inventory_import")
            status = "applied"
        db.executemany(
            "INSERT INTO import_rows(batch_id,row_number,external_id,status,message,raw_data) "
            "VALUES (?,?,?,?,?,?)",
            [(batch_id, *row) for row in audit_rows],
        )
        db.execute(
            "UPDATE import_batches SET status=?,accepted_count=?,rejected_count=?,warning_count=?,"
            "completed_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, accepted, rejected, warnings, batch_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"batch_id": batch_id, "accepted": accepted, "rejected": rejected, "warnings": warnings}

