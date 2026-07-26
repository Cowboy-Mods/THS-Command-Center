from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path


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
    try:
        db.execute("SAVEPOINT inventory_import")
        for number, row in enumerate(rows, 2):
            errors: list[str] = []
            if not _truthy(row.get("verified_status", "")) and not allow_unverified:
                errors.append("row is not verified")
            tracking = row.get("tracking_method", "")
            if tracking not in {"quantity", "individual", "lot"}:
                errors.append("invalid tracking_method")
            try:
                quantity = float(row.get("quantity") or 0)
                count = int(row.get("instance_count") or 0)
                remaining = float(row.get("remaining_quantity") or quantity)
                if min(quantity, count, remaining) < 0:
                    errors.append("quantities cannot be negative")
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
                category = db.execute("SELECT id FROM categories WHERE name=?", (row["category"],)).fetchone()
                if not category:
                    category_id = db.execute(
                        "INSERT INTO categories(name) VALUES (?)", (row["category"],)
                    ).lastrowid
                else:
                    category_id = category["id"]
                item_type = db.execute("SELECT id FROM item_types WHERE name=?", (row["item_type"],)).fetchone()
                if not item_type:
                    item_type_id = db.execute(
                        "INSERT INTO item_types(category_id,name,tracking_method,default_unit_id) VALUES (?,?,?,?)",
                        (category_id, row["item_type"], tracking, unit["id"]),
                    ).lastrowid
                else:
                    item_type_id = item_type["id"]
                maker = db.execute("SELECT id FROM manufacturers WHERE name=?", (row["manufacturer"],)).fetchone()
                maker_id = maker["id"] if maker else db.execute(
                    "INSERT INTO manufacturers(name) VALUES (?)", (row["manufacturer"],)
                ).lastrowid
                key = (item_type_id, maker_id, row["product_name"], row.get("product_line",""), row.get("variant",""))
                product = db.execute(
                    "SELECT id FROM catalog_items WHERE item_type_id=? AND manufacturer_id=? "
                    "AND name=? AND product_line=? AND variant=?", key
                ).fetchone()
                if product:
                    product_id = product["id"]
                    warnings += 1
                else:
                    product_id = db.execute(
                        "INSERT INTO catalog_items(item_type_id,manufacturer_id,name,product_line,variant,base_unit_id,notes) "
                        "VALUES (?,?,?,?,?,?,?)", (*key, unit["id"], row.get("notes"))
                    ).lastrowid
                if tracking == "individual":
                    for _ in range(count):
                        db.execute(
                            "INSERT INTO inventory_instances(catalog_item_id,state,location_id,original_quantity,"
                            "remaining_quantity,unit_id,verified) VALUES (?,?,?,?,?,?,1)",
                            (product_id, row.get("state") or "sealed", location["id"], quantity, remaining, unit["id"]),
                        )
                else:
                    db.execute(
                        "INSERT INTO stock_lots(catalog_item_id,location_id,quantity,unit_id,verified) VALUES (?,?,?,?,1)",
                        (product_id, location["id"], quantity, unit["id"]),
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

