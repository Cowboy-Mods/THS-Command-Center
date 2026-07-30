from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import date, time as clock_time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .actions import ActionContext, InventoryActionError, InventoryActionService
from .db import connect


class PurchaseReceivingError(ValueError):
    """A Purchase Registry transition or receipt is invalid, stale, or replayed."""


class PurchaseReceivingService:
    MODULE = "purchase-registry-receiving"
    MAX_REVIEW_AGE_SECONDS = 30 * 60
    STATUSES = {
        "ordered", "shipped", "delivered",
        "partially_received", "received", "canceled",
    }

    def __init__(self, database, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def receiving_status(self, purchase_id: int) -> dict:
        with closing(connect(self.database)) as db:
            return self._snapshot(db, purchase_id)

    def review_transition(self, form: dict) -> dict:
        purchase_id = self._positive_int(form.get("purchase_id"), "purchase")
        actor = self._text(form.get("actor"), "actor", 100)
        reason = self._text(form.get("reason"), "reason", 2000)
        target = self._text(form.get("new_status"), "new status", 30).lower()
        if target not in {"shipped", "delivered", "canceled"}:
            raise PurchaseReceivingError("select Shipped, Delivered, or Canceled")
        event_date, event_time, precision = self._event_time(form, "event")
        with closing(connect(self.database)) as db:
            snapshot = self._snapshot(db, purchase_id)
            current = snapshot["status"]
            allowed = {
                "ordered": {"shipped", "delivered", "canceled"},
                "shipped": {"delivered", "canceled"},
                "delivered": {"canceled"},
                "partially_received": set(),
                "received": set(),
                "canceled": set(),
            }
            if target not in allowed[current]:
                raise PurchaseReceivingError(
                    f"purchase cannot transition from {current} to {target}"
                )
            if target == "canceled" and snapshot["has_receipts"]:
                raise PurchaseReceivingError(
                    "a purchase with received quantity cannot be canceled"
                )
        values = {
            "version": 1,
            "module": self.MODULE,
            "action": "transition_status",
            "reviewed_at": int(time.time()),
            "request_nonce": uuid.uuid4().hex,
            "transition_uuid": str(uuid.uuid4()),
            "actor": actor,
            "reason": reason,
            "purchase": snapshot,
            "new_status": target,
            "physical_event_date": event_date,
            "physical_event_time": event_time,
            "event_time_precision": precision,
        }
        return self._review(values)

    def commit_transition(self, token: str, *, confirmed: bool) -> dict:
        values, body = self._verified_action(token, confirmed, "transition_status")
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            self._reject_replay(db, values["request_nonce"])
            current = self._snapshot(db, values["purchase"]["purchase"]["id"])
            if current != values["purchase"]:
                raise PurchaseReceivingError(
                    "purchase changed after preview; review the transition again"
                )
            previous = current["status"]
            target = values["new_status"]
            allowed = {
                "ordered": {"shipped", "delivered", "canceled"},
                "shipped": {"delivered", "canceled"},
                "delivered": {"canceled"},
            }
            if target not in allowed.get(previous, set()):
                raise PurchaseReceivingError(
                    f"purchase cannot transition from {previous} to {target}"
                )
            if target == "canceled" and current["has_receipts"]:
                raise PurchaseReceivingError(
                    "a purchase with received quantity cannot be canceled"
                )
            db.execute(
                """UPDATE purchase_fulfillment_state
                SET transport_status=?,state_version=state_version+1,
                last_transition_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                WHERE purchase_order_id=? AND state_version=?""",
                (
                    target, current["purchase"]["id"],
                    current["fulfillment"]["state_version"],
                ),
            )
            if db.total_changes != 1:
                raise PurchaseReceivingError(
                    "purchase sequence changed after preview; review again"
                )
            new_snapshot = self._snapshot(db, current["purchase"]["id"])
            history_id = self._history(
                db, values, body, previous, new_snapshot["status"],
                current, new_snapshot,
            )
            db.commit()
            return {
                "purchase_id": current["purchase"]["id"],
                "purchase_number": current["purchase"]["purchase_number"],
                "previous_status": previous,
                "status": new_snapshot["status"],
                "history_id": history_id,
                "transition_uuid": values["transition_uuid"],
            }
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise PurchaseReceivingError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def review_receipt(self, form: dict) -> dict:
        purchase_id = self._positive_int(form.get("purchase_id"), "purchase")
        actor = self._text(form.get("actor"), "actor", 100)
        reason = self._text(form.get("reason"), "reason", 2000)
        receipt_date, receipt_time, precision = self._event_time(form, "receipt")
        note = self._optional_text(form.get("note"), 2000)
        raw_lines = form.get("lines")
        if not isinstance(raw_lines, list) or not raw_lines:
            raise PurchaseReceivingError("select at least one purchase line")
        evidence_uuids = form.get("evidence_uuids")
        if not isinstance(evidence_uuids, list) or not evidence_uuids:
            raise PurchaseReceivingError("select delivery evidence for the receipt")
        if len(set(evidence_uuids)) != len(evidence_uuids):
            raise PurchaseReceivingError("delivery evidence cannot be selected twice")

        with closing(connect(self.database)) as db:
            snapshot = self._snapshot(db, purchase_id)
            if snapshot["status"] in {"received", "canceled"}:
                raise PurchaseReceivingError(
                    f"{snapshot['status']} purchase cannot be received"
                )
            evidence = self._evidence(db, purchase_id, evidence_uuids)
            lines = self._review_receipt_lines(db, snapshot, raw_lines)

        values = {
            "version": 1,
            "module": self.MODULE,
            "action": "receive_purchase",
            "reviewed_at": int(time.time()),
            "request_nonce": uuid.uuid4().hex,
            "receipt_uuid": str(uuid.uuid4()),
            "transition_uuid": str(uuid.uuid4()),
            "actor": actor,
            "reason": reason,
            "note": note,
            "purchase": snapshot,
            "physical_receipt_date": receipt_date,
            "physical_receipt_time": receipt_time,
            "receipt_time_precision": precision,
            "evidence": evidence,
            "evidence_links": [
                {
                    "link_uuid": str(uuid.uuid4()),
                    "evidence_uuid": row["evidence_uuid"],
                }
                for row in evidence
            ],
            "lines": lines,
        }
        return self._review(values)

    def commit_receipt(self, token: str, *, confirmed: bool) -> dict:
        values, body = self._verified_action(token, confirmed, "receive_purchase")
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            self._reject_replay(db, values["request_nonce"])
            purchase_id = values["purchase"]["purchase"]["id"]
            current = self._snapshot(db, purchase_id)
            if current != values["purchase"]:
                raise PurchaseReceivingError(
                    "purchase or line receipt state changed after preview; review again"
                )
            if current["status"] in {"received", "canceled"}:
                raise PurchaseReceivingError(
                    f"{current['status']} purchase cannot be received"
                )
            evidence = self._evidence(
                db, purchase_id,
                [row["evidence_uuid"] for row in values["evidence"]],
            )
            if evidence != values["evidence"]:
                raise PurchaseReceivingError(
                    "delivery evidence changed after preview; review again"
                )
            for row in evidence:
                digest, size = self._file_identity(Path(row["file_path"]))
                if digest != row["sha256"] or size != row["file_size"]:
                    raise PurchaseReceivingError(
                        "delivery evidence file is missing or changed; review again"
                    )
            self._revalidate_receipt_lines(db, current, values["lines"])

            receipt_id = db.execute(
                """INSERT INTO purchase_receipts(
                receipt_uuid,purchase_order_id,request_nonce,actor,
                physical_receipt_date,physical_receipt_time,receipt_time_precision,note)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    values["receipt_uuid"], purchase_id, values["request_nonce"],
                    values["actor"], values["physical_receipt_date"],
                    values["physical_receipt_time"], values["receipt_time_precision"],
                    values["note"],
                ),
            ).lastrowid
            service = InventoryActionService(
                db,
                ActionContext(
                    actor=values["actor"], module=self.MODULE, origin="user"
                ),
            )
            results = []
            for line in values["lines"]:
                receipt_line_id = db.execute(
                    """INSERT INTO purchase_receipt_lines(
                    receipt_line_uuid,purchase_receipt_id,purchase_order_line_id,
                    quantity_received,unit_label,condition,catalog_item_id,
                    tracking_policy,location_id,lot_number,expiration_date,note)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        line["receipt_line_uuid"], receipt_id,
                        line["purchase_order_line_id"], line["quantity_received"],
                        line["unit_label"], line["condition"], line["catalog_item_id"],
                        line["tracking_policy"], line["location_id"],
                        line["lot_number"], line["expiration_date"], line["note"],
                    ),
                ).lastrowid
                inventory_ids = self._create_inventory(
                    db, service, receipt_line_id, line,
                    current["purchase"]["purchase_number"], values["reason"],
                )
                results.append({
                    "receipt_line_id": receipt_line_id,
                    "line_number": line["line_number"],
                    "inventory_ids": inventory_ids,
                })
            for link, evidence_row in zip(values["evidence_links"], evidence):
                db.execute(
                    """INSERT INTO purchase_receipt_evidence(
                    link_uuid,purchase_receipt_id,purchase_evidence_id)
                    VALUES (?,?,?)""",
                    (link["link_uuid"], receipt_id, evidence_row["id"]),
                )
            db.execute(
                """UPDATE purchase_fulfillment_state
                SET state_version=state_version+1,updated_at=CURRENT_TIMESTAMP
                WHERE purchase_order_id=? AND state_version=?""",
                (purchase_id, current["fulfillment"]["state_version"]),
            )
            new_snapshot = self._snapshot(db, purchase_id)
            history_id = self._history(
                db, values, body, current["status"], new_snapshot["status"],
                current, new_snapshot,
            )
            db.commit()
            return {
                "purchase_id": purchase_id,
                "purchase_number": current["purchase"]["purchase_number"],
                "receipt_id": receipt_id,
                "receipt_uuid": values["receipt_uuid"],
                "history_id": history_id,
                "status": new_snapshot["status"],
                "lines": results,
            }
        except (sqlite3.IntegrityError, InventoryActionError) as exc:
            db.rollback()
            raise PurchaseReceivingError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _create_inventory(
        self, db, service, receipt_line_id, line, purchase_number, reason,
    ):
        policy = line["tracking_policy"]
        if policy == "non_inventory":
            return []
        created = []
        if policy == "individual":
            per_instance_quantity = line["per_instance_quantity"]
            for identity in line["inventory_identities"]:
                instance_id = service.add_individual_instance(
                    line["catalog_item_id"],
                    state="sealed",
                    location_id=line["location_id"],
                    original_quantity=per_instance_quantity,
                    remaining_quantity=per_instance_quantity,
                    unit_id=line["base_unit_id"],
                    permanent_id=identity["permanent_id"],
                    condition=line["condition"],
                    lot_number=line["lot_number"],
                    expires_at=line["expiration_date"],
                    notes=line["note"],
                    verified=True,
                    reason=reason,
                    order_ref=purchase_number,
                    action_uuid=identity["action_uuid"],
                )
                db.execute(
                    """INSERT INTO purchase_receipt_inventory_links(
                    link_uuid,purchase_receipt_line_id,inventory_instance_id,
                    represented_quantity) VALUES (?,?,?,?)""",
                    (
                        identity["link_uuid"], receipt_line_id, instance_id, "1",
                    ),
                )
                created.append(instance_id)
            return created
        identity = line["inventory_identities"][0]
        stock_lot_id = service.add_stock_lot(
            line["catalog_item_id"],
            location_id=line["location_id"],
            quantity=float(Decimal(line["quantity_received"])),
            unit_id=line["base_unit_id"],
            lot_number=line["lot_number"],
            condition=line["condition"],
            expires_at=line["expiration_date"],
            verified=True,
            reason=reason,
            action_uuid=identity["action_uuid"],
        )
        db.execute(
            """INSERT INTO purchase_receipt_inventory_links(
            link_uuid,purchase_receipt_line_id,stock_lot_id,represented_quantity)
            VALUES (?,?,?,?)""",
            (
                identity["link_uuid"], receipt_line_id, stock_lot_id,
                line["quantity_received"],
            ),
        )
        return [stock_lot_id]

    def _review_receipt_lines(self, db, snapshot, raw_lines):
        by_id = {row["id"]: row for row in snapshot["lines"]}
        seen = set()
        result = []
        next_by_prefix = {}
        for raw in raw_lines:
            if not isinstance(raw, dict):
                raise PurchaseReceivingError("receipt lines are invalid")
            line_id = self._positive_int(
                raw.get("purchase_order_line_id"), "purchase line"
            )
            if line_id in seen:
                raise PurchaseReceivingError(
                    "a purchase line cannot be selected twice"
                )
            seen.add(line_id)
            source = by_id.get(line_id)
            if not source:
                raise PurchaseReceivingError(
                    "receipt line does not belong to this purchase"
                )
            quantity = self._quantity(
                raw.get("quantity_received"), f"line {source['line_number']} quantity"
            )
            outstanding = Decimal(source["quantity_outstanding"])
            if quantity > outstanding:
                raise PurchaseReceivingError(
                    f"line {source['line_number']} receipt exceeds its outstanding quantity"
                )
            policy = source["inventory_tracking_intent"]
            condition = self._text(raw.get("condition"), "condition", 20).lower()
            if condition not in {"new", "good", "damaged"}:
                raise PurchaseReceivingError("select a valid received condition")
            catalog_item_id = self._optional_positive_int(raw.get("catalog_item_id"))
            location_id = self._optional_positive_int(raw.get("location_id"))
            catalog = None
            if policy == "non_inventory":
                if catalog_item_id or location_id:
                    raise PurchaseReceivingError(
                        "non-inventory receipt lines cannot create inventory"
                    )
            else:
                if not catalog_item_id or not location_id:
                    raise PurchaseReceivingError(
                        f"line {source['line_number']} requires catalog and location resolution"
                    )
                catalog = db.execute(
                    """SELECT ci.id,ci.base_unit_id,it.tracking_method,it.id_prefix,
                    u.code unit_code,u.name unit_name
                    FROM catalog_items ci
                    JOIN item_types it ON it.id=ci.item_type_id
                    JOIN units u ON u.id=ci.base_unit_id
                    WHERE ci.id=? AND ci.archived_at IS NULL""",
                    (catalog_item_id,),
                ).fetchone()
                if not catalog or catalog["tracking_method"] != policy:
                    raise PurchaseReceivingError(
                        f"line {source['line_number']} catalog tracking does not match purchase intent"
                    )
                location = db.execute(
                    "SELECT id,name FROM locations WHERE id=? AND archived_at IS NULL",
                    (location_id,),
                ).fetchone()
                if not location:
                    raise PurchaseReceivingError("receiving location was not found")
            if policy == "individual" and quantity != quantity.to_integral_value():
                raise PurchaseReceivingError(
                    "individually tracked receipt quantity must be a whole number"
                )
            identities = []
            if policy == "individual":
                prefix = catalog["id_prefix"]
                if not prefix:
                    raise PurchaseReceivingError(
                        "individually tracked item type needs a permanent-ID prefix"
                    )
                start = next_by_prefix.get(prefix)
                if start is None:
                    start = self._next_permanent_number(db, prefix)
                for number in range(start, start + int(quantity)):
                    identities.append({
                        "permanent_id": f"{prefix}-{number:06d}",
                        "action_uuid": str(uuid.uuid4()),
                        "link_uuid": str(uuid.uuid4()),
                    })
                next_by_prefix[prefix] = start + int(quantity)
            elif policy in {"quantity", "lot"}:
                identities.append({
                    "action_uuid": str(uuid.uuid4()),
                    "link_uuid": str(uuid.uuid4()),
                })
            per_instance_quantity = None
            if policy == "individual":
                per_instance_quantity = self._individual_quantity(
                    db, catalog_item_id, catalog["base_unit_id"]
                )
            result.append({
                "receipt_line_uuid": str(uuid.uuid4()),
                "purchase_order_line_id": line_id,
                "line_number": source["line_number"],
                "line_uuid": source["line_uuid"],
                "quantity_received": self._decimal_text(quantity),
                "quantity_outstanding_before": source["quantity_outstanding"],
                "unit_label": source["unit_label"],
                "condition": condition,
                "catalog_item_id": catalog_item_id,
                "tracking_policy": policy,
                "location_id": location_id,
                "lot_number": self._optional_text(raw.get("lot_number"), 200),
                "expiration_date": self._optional_date(raw.get("expiration_date")),
                "note": self._optional_text(raw.get("note"), 1000),
                "base_unit_id": catalog["base_unit_id"] if catalog else None,
                "per_instance_quantity": per_instance_quantity,
                "inventory_identities": identities,
            })
        return result

    def _revalidate_receipt_lines(self, db, snapshot, lines):
        rebuilt = []
        next_by_prefix = {}
        # Re-run immutable catalog/location and outstanding checks without generating IDs.
        by_id = {row["id"]: row for row in snapshot["lines"]}
        for line in lines:
            source = by_id.get(line["purchase_order_line_id"])
            if (
                not source
                or source["line_uuid"] != line["line_uuid"]
                or source["quantity_outstanding"] != line["quantity_outstanding_before"]
            ):
                raise PurchaseReceivingError(
                    "purchase line changed after preview; review again"
                )
            quantity = Decimal(line["quantity_received"])
            if quantity > Decimal(source["quantity_outstanding"]):
                raise PurchaseReceivingError("receipt exceeds outstanding quantity")
            if line["tracking_policy"] != source["inventory_tracking_intent"]:
                raise PurchaseReceivingError("purchase tracking intent changed")
            if line["tracking_policy"] != "non_inventory":
                catalog = db.execute(
                    """SELECT ci.base_unit_id,it.tracking_method,it.id_prefix
                    FROM catalog_items ci JOIN item_types it ON it.id=ci.item_type_id
                    WHERE ci.id=? AND ci.archived_at IS NULL""",
                    (line["catalog_item_id"],),
                ).fetchone()
                if (
                    not catalog
                    or catalog["tracking_method"] != line["tracking_policy"]
                    or catalog["base_unit_id"] != line["base_unit_id"]
                ):
                    raise PurchaseReceivingError(
                        "catalog tracking changed after preview; review again"
                    )
                if not db.execute(
                    "SELECT 1 FROM locations WHERE id=? AND archived_at IS NULL",
                    (line["location_id"],),
                ).fetchone():
                    raise PurchaseReceivingError(
                        "receiving location changed after preview; review again"
                    )
                if line["tracking_policy"] == "individual":
                    ids = [row["permanent_id"] for row in line["inventory_identities"]]
                    prefix = catalog["id_prefix"]
                    expected_start = next_by_prefix.get(prefix)
                    if expected_start is None:
                        expected_start = self._next_permanent_number(db, prefix)
                    expected = [
                        f"{prefix}-{number:06d}"
                        for number in range(expected_start, expected_start + len(ids))
                    ]
                    if ids != expected:
                        raise PurchaseReceivingError(
                            "inventory ID sequence changed after preview; review again"
                        )
                    next_by_prefix[prefix] = expected_start + len(ids)
            rebuilt.append(line["purchase_order_line_id"])
        if len(rebuilt) != len(set(rebuilt)):
            raise PurchaseReceivingError("duplicate receipt line detected")

    def _snapshot(self, db, purchase_id):
        purchase = db.execute(
            """SELECT po.*,pv.name vendor_name
            FROM purchase_orders po JOIN purchase_vendors pv ON pv.id=po.vendor_id
            WHERE po.id=?""",
            (purchase_id,),
        ).fetchone()
        if not purchase:
            raise PurchaseReceivingError("purchase not found")
        fulfillment = db.execute(
            """SELECT pfs.*,pors.status
            FROM purchase_fulfillment_state pfs
            JOIN purchase_order_receiving_status pors
              ON pors.purchase_order_id=pfs.purchase_order_id
            WHERE pfs.purchase_order_id=?""",
            (purchase_id,),
        ).fetchone()
        lines = [
            dict(row)
            for row in db.execute(
                """SELECT pol.*,plrs.quantity_received,plrs.quantity_outstanding
                FROM purchase_order_lines pol
                JOIN purchase_line_receiving_status plrs
                  ON plrs.purchase_order_line_id=pol.id
                WHERE pol.purchase_order_id=? ORDER BY pol.line_number""",
                (purchase_id,),
            )
        ]
        return {
            "purchase": dict(purchase),
            "fulfillment": dict(fulfillment),
            "lines": lines,
            "status": fulfillment["status"],
            "has_receipts": any(
                Decimal(row["quantity_received"]) > 0 for row in lines
            ),
        }

    def _evidence(self, db, purchase_id, evidence_uuids):
        placeholders = ",".join("?" for _ in evidence_uuids)
        rows = [
            dict(row)
            for row in db.execute(
                f"""SELECT id,evidence_uuid,purchase_order_id,evidence_scope,
                evidence_type,file_path,sha256,file_size,caption,document_date,
                added_by,added_at
                FROM purchase_evidence
                WHERE purchase_order_id=? AND evidence_scope='delivery'
                  AND evidence_uuid IN ({placeholders})
                ORDER BY id""",
                (purchase_id, *evidence_uuids),
            )
        ]
        if len(rows) != len(evidence_uuids):
            raise PurchaseReceivingError(
                "select delivery evidence belonging to this purchase"
            )
        return rows

    def _history(self, db, values, body, previous, new, old_snapshot, new_snapshot):
        return db.execute(
            """INSERT INTO purchase_fulfillment_history(
            transition_uuid,request_nonce,purchase_order_id,action_type,
            previous_status,new_status,previous_snapshot,new_snapshot,payload_sha256,
            reason,actor,physical_event_date,physical_event_time,event_time_precision)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                values["transition_uuid"], values["request_nonce"],
                old_snapshot["purchase"]["id"], values["action"], previous, new,
                self._json(old_snapshot), self._json(new_snapshot),
                hashlib.sha256(body).hexdigest(), values["reason"], values["actor"],
                values.get("physical_event_date", values.get("physical_receipt_date")),
                values.get("physical_event_time", values.get("physical_receipt_time")),
                values.get("event_time_precision", values.get("receipt_time_precision")),
            ),
        ).lastrowid

    def _reject_replay(self, db, nonce):
        if db.execute(
            "SELECT 1 FROM purchase_fulfillment_history WHERE request_nonce=?",
            (nonce,),
        ).fetchone() or db.execute(
            "SELECT 1 FROM purchase_receipts WHERE request_nonce=?", (nonce,)
        ).fetchone():
            raise PurchaseReceivingError("this purchase preview was already used")

    def _review(self, values):
        body = self._canonical(values)
        return {
            "token": self._sign(body),
            "values": values,
            "payload_sha256": hashlib.sha256(body).hexdigest(),
        }

    def _verified_action(self, token, confirmed, action):
        if not confirmed:
            raise PurchaseReceivingError("explicit confirmation is required")
        values, body = self._verify(token)
        if (
            values.get("version") != 1
            or values.get("module") != self.MODULE
            or values.get("action") != action
        ):
            raise PurchaseReceivingError("purchase receiving preview is invalid")
        nonce = values.get("request_nonce")
        if (
            not isinstance(nonce, str)
            or len(nonce) != 32
            or any(char not in "0123456789abcdef" for char in nonce)
        ):
            raise PurchaseReceivingError("purchase preview nonce is invalid")
        return values, body

    def _sign(self, body):
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return self._b64(body) + "." + self._b64(signature)

    def _verify(self, token):
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            signature = self._unb64(signature_text)
            if self._b64(body) != body_text or not hmac.compare_digest(
                signature, hmac.new(self.secret, body, hashlib.sha256).digest()
            ):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PurchaseReceivingError(
                "purchase receiving preview signature is invalid"
            ) from exc
        age = int(time.time()) - values.get("reviewed_at", 0)
        if age < -60 or age > self.MAX_REVIEW_AGE_SECONDS:
            raise PurchaseReceivingError(
                "purchase receiving preview expired; review again"
            )
        return values, body

    @staticmethod
    def _next_permanent_number(db, prefix):
        value = db.execute(
            """SELECT MAX(CAST(SUBSTR(permanent_id,LENGTH(?)+2) AS INTEGER))
            FROM inventory_instances WHERE permanent_id LIKE ?""",
            (prefix, f"{prefix}-%"),
        ).fetchone()[0] or 0
        return value + 1

    @staticmethod
    def _individual_quantity(db, catalog_item_id, base_unit_id):
        row = db.execute(
            """SELECT av.numeric_value
            FROM catalog_item_attribute_values av
            JOIN attribute_definitions ad ON ad.id=av.attribute_definition_id
            WHERE av.catalog_item_id=? AND ad.name='nominal_weight_g'""",
            (catalog_item_id,),
        ).fetchone()
        if row and row[0] is not None:
            return float(row[0])
        unit = db.execute(
            "SELECT code,dimension FROM units WHERE id=?", (base_unit_id,)
        ).fetchone()
        if unit and unit["dimension"] == "count":
            return 1.0
        raise PurchaseReceivingError(
            "individually tracked catalog item needs a verified per-instance quantity"
        )

    @classmethod
    def _event_time(cls, form, label):
        date_text = cls._text(
            form.get(f"physical_{label}_date"), f"physical {label} date", 10
        )
        try:
            date.fromisoformat(date_text)
        except ValueError as exc:
            raise PurchaseReceivingError(
                f"physical {label} date must use YYYY-MM-DD"
            ) from exc
        precision = cls._text(
            form.get(f"{label}_time_precision"), f"{label} time precision", 20
        ).lower()
        if precision not in {"exact", "estimated", "date_only"}:
            raise PurchaseReceivingError(
                f"{label} time precision must be exact, estimated, or date-only"
            )
        time_text = cls._optional_text(form.get(f"physical_{label}_time"), 8)
        if precision == "date_only":
            if time_text:
                raise PurchaseReceivingError(
                    f"date-only {label} cannot include a physical time"
                )
            return date_text, None, precision
        if not time_text:
            raise PurchaseReceivingError(
                f"{precision} {label} requires a physical time"
            )
        try:
            parsed = clock_time.fromisoformat(time_text)
        except ValueError as exc:
            raise PurchaseReceivingError(
                f"physical {label} time must be valid"
            ) from exc
        return date_text, parsed.replace(microsecond=0).isoformat(), precision

    @staticmethod
    def _file_identity(path):
        if not path.is_file():
            raise PurchaseReceivingError("delivery evidence file is missing")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest(), path.stat().st_size

    @staticmethod
    def _quantity(value, label):
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise PurchaseReceivingError(f"{label} is invalid") from exc
        if not parsed.is_finite() or parsed <= 0 or parsed.as_tuple().exponent < -3:
            raise PurchaseReceivingError(
                f"{label} must be positive with at most three decimals"
            )
        return parsed

    @staticmethod
    def _decimal_text(value):
        return format(value.normalize(), "f")

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _canonical(value):
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode()

    @staticmethod
    def _text(value, label, maximum):
        value = str(value or "").strip()
        if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
            raise PurchaseReceivingError(f"{label} is required or invalid")
        return value

    @staticmethod
    def _optional_text(value, maximum):
        value = str(value or "").strip()
        if not value:
            return None
        if len(value) > maximum or any(ord(char) < 32 for char in value):
            raise PurchaseReceivingError("optional receipt value is invalid")
        return value

    @staticmethod
    def _positive_int(value, label):
        try:
            parsed = int(value)
            if parsed <= 0:
                raise ValueError
            return parsed
        except (TypeError, ValueError) as exc:
            raise PurchaseReceivingError(f"{label} is required") from exc

    @staticmethod
    def _optional_positive_int(value):
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
            if parsed <= 0:
                raise ValueError
            return parsed
        except (TypeError, ValueError) as exc:
            raise PurchaseReceivingError("receipt reference is invalid") from exc

    @staticmethod
    def _optional_date(value):
        value = str(value or "").strip()
        if not value:
            return None
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise PurchaseReceivingError(
                "expiration date must use YYYY-MM-DD"
            ) from exc
        return value

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    @staticmethod
    def _unb64(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
