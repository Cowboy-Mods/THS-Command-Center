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
from dataclasses import dataclass

from .actions import ActionContext, InventoryActionError, InventoryActionService
from .db import connect


class ReplaceSpoolError(ValueError):
    """A guided spool replacement is invalid, stale, replayed, or incomplete."""


@dataclass(frozen=True)
class ReplacementReview:
    token: str
    values: dict


class ReplaceActiveFilamentSpoolWorkflow:
    MODULE = "filament-spool-replacement-ui"
    MAX_REVIEW_AGE_SECONDS = 30 * 60

    def __init__(self, database, secret: bytes | None = None):
        self.database = database
        self.secret = secret or secrets.token_bytes(32)

    def options(self, filters: dict[str, str] | None = None) -> dict:
        filters = filters or {}
        with closing(connect(self.database)) as db:
            schema19_ready = bool(
                db.execute(
                    """SELECT 1 FROM schema_migrations
                    WHERE name='019_flexible_spool_replacement.sql'"""
                ).fetchone()
            )
            current = [
                dict(row) for row in db.execute(
                    self._spool_select(include_ams=True) +
                    """ WHERE ii.state='loaded' AND ii.archived_at IS NULL
                    ORDER BY e.name,es.slot_number"""
                )
            ]
            clauses = ["ii.state='sealed'", "ii.archived_at IS NULL"]
            params: list[str] = []
            q = filters.get("q", "").strip()
            manufacturer = filters.get("manufacturer", "").strip()
            material = filters.get("material", "").strip()
            color = filters.get("color", "").strip()
            if q:
                clauses.append(
                    "(ii.permanent_id LIKE ? OR m.name LIKE ? OR ci.product_line LIKE ? "
                    "OR ci.variant LIKE ? OR mat.text_value LIKE ?)"
                )
                params.extend([f"%{q}%"] * 5)
            for column, value in (
                ("m.name", manufacturer), ("mat.text_value", material), ("ci.variant", color)
            ):
                if value:
                    clauses.append(f"{column}=?")
                    params.append(value)
            replacements = [
                dict(row) for row in db.execute(
                    self._spool_select() + " WHERE " + " AND ".join(clauses) +
                    " ORDER BY m.name,ci.product_line,ci.variant,ii.permanent_id",
                    params,
                )
            ]
            facets = {
                "manufacturers": self._values(db, "m.name"),
                "materials": self._values(db, "mat.text_value"),
                "colors": self._values(db, "ci.variant"),
            }
            slots = [
                dict(row) for row in db.execute(
                    """SELECT es.id,e.name equipment_name,es.slot_number,
                    aa.instance_id occupant_instance_id,ii.permanent_id occupant_permanent_id
                    FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
                    LEFT JOIN ams_assignments aa ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                    LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
                    WHERE e.equipment_type='AMS' AND e.archived_at IS NULL
                    ORDER BY e.name,es.slot_number"""
                )
            ]
            incoming_spools = [
                dict(row) for row in db.execute(
                    self._spool_select_with_optional_ams() +
                    """ WHERE ii.state IN ('sealed','open','loaded')
                    AND ii.archived_at IS NULL
                    ORDER BY CASE ii.state
                      WHEN 'open' THEN 1 WHEN 'loaded' THEN 2 ELSE 3 END,
                    m.name,ci.product_line,ci.variant,ii.permanent_id"""
                )
            ]
            storage_locations = [
                dict(row) for row in db.execute(
                    """SELECT id,name,kind FROM locations
                    WHERE kind='storage' AND archived_at IS NULL
                    ORDER BY name"""
                )
            ]
            return {
                "schema19_ready": schema19_ready,
                "current_spools": current,
                "replacement_spools": replacements,
                "incoming_spools": incoming_spools,
                "storage_locations": storage_locations,
                "slots": slots,
                "filters": {
                    "q": q, "manufacturer": manufacturer,
                    "material": material, "color": color,
                },
                **facets,
            }

    def review(self, form: dict[str, str]) -> ReplacementReview:
        if (
            str(form.get("outgoing_disposition", "")).strip()
            or str(form.get("incoming_disposition", "")).strip()
        ):
            return self._review_flexible(form)
        if form.get("confirm_empty") != "yes":
            raise ReplaceSpoolError('confirm "This spool is now empty."')
        current_id = self._positive_int(form, "current_instance_id", "select the active spool")
        replacement_id = self._positive_int(
            form, "replacement_instance_id", "select a sealed replacement spool"
        )
        if current_id == replacement_id:
            raise ReplaceSpoolError("current and replacement spools must be different")
        actor = self._text(form, "actor", 100)
        reason = self._optional(form, "reason", 500)
        print_job_name = self._optional(form, "print_job_name", 160)
        approximate_layer = self._optional_nonnegative_int(
            form, "approximate_layer", "approximate layer"
        )
        printer = self._optional(form, "printer", 120)
        plate = self._optional(form, "plate", 120)
        operational_note = self._optional(form, "operational_note", 1000)

        with closing(connect(self.database)) as db:
            current = self._active_spool(db, current_id)
            if not current:
                raise ReplaceSpoolError("current spool must be actively loaded in an AMS")
            replacement = self._sealed_spool(db, replacement_id)
            if not replacement:
                raise ReplaceSpoolError("replacement spool must be sealed and active")
            destination_id = (
                self._positive_int(form, "destination_slot_id", "select a destination AMS slot")
                if str(form.get("destination_slot_id", "")).strip()
                else current["slot_id"]
            )
            destination = db.execute(
                """SELECT es.id,e.name equipment_name,es.slot_number,
                aa.instance_id occupant_instance_id,ii.permanent_id occupant_permanent_id
                FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
                LEFT JOIN ams_assignments aa ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
                WHERE es.id=? AND e.equipment_type='AMS' AND e.archived_at IS NULL""",
                (destination_id,),
            ).fetchone()
            if not destination:
                raise ReplaceSpoolError("destination AMS slot does not exist")
            if (
                destination["occupant_instance_id"] is not None
                and destination["occupant_instance_id"] != current_id
            ):
                raise ReplaceSpoolError("destination AMS slot is occupied by another spool")
            values = {
                "version": 1,
                "reviewed_at": int(time.time()),
                "review_nonce": uuid.uuid4().hex,
                "module": self.MODULE,
                "actor": actor,
                "reason": reason,
                "print_job_name": print_job_name,
                "approximate_layer": approximate_layer,
                "printer": printer,
                "plate": plate,
                "operational_note": operational_note,
                "current": current,
                "replacement": replacement,
                "destination": dict(destination),
            }
        return ReplacementReview(self._sign(values), values)

    def commit(self, token: str) -> dict:
        values = self._verify(token)
        if values["version"] == 2:
            return self._commit_flexible(values)
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            current = self._active_spool(db, values["current"]["id"])
            replacement = self._sealed_spool(db, values["replacement"]["id"])
            if current != values["current"]:
                raise ReplaceSpoolError("active spool changed after preview; review again")
            if replacement != values["replacement"]:
                raise ReplaceSpoolError("replacement spool changed after preview; review again")
            destination = db.execute(
                """SELECT es.id,e.name equipment_name,es.slot_number,
                aa.instance_id occupant_instance_id,ii.permanent_id occupant_permanent_id
                FROM equipment_slots es JOIN equipment e ON e.id=es.equipment_id
                LEFT JOIN ams_assignments aa ON aa.slot_id=es.id AND aa.unloaded_at IS NULL
                LEFT JOIN inventory_instances ii ON ii.id=aa.instance_id
                WHERE es.id=? AND e.equipment_type='AMS' AND e.archived_at IS NULL""",
                (values["destination"]["id"],),
            ).fetchone()
            if not destination or dict(destination) != values["destination"]:
                raise ReplaceSpoolError("destination AMS slot changed after preview; review again")
            service = InventoryActionService(
                db, ActionContext(
                    actor=values["actor"], module=self.MODULE, origin="user"
                ),
            )
            result = service.replace_active_filament_spool(
                current["id"], replacement["id"], destination["id"],
                reason=values["reason"], review_nonce=values["review_nonce"],
                print_job_name=values["print_job_name"],
                approximate_layer=values["approximate_layer"],
                printer=values["printer"], plate=values["plate"],
                operational_note=values["operational_note"],
            )
            db.commit()
            return {**values, **result}
        except (InventoryActionError, sqlite3.IntegrityError) as exc:
            db.rollback()
            message = (
                "this preview was already used; start a new replacement"
                if "review_nonce" in str(exc) or "UNIQUE constraint failed" in str(exc)
                else str(exc)
            )
            raise ReplaceSpoolError(message) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _active_spool(self, db, instance_id: int) -> dict | None:
        row = db.execute(
            self._spool_select(include_ams=True) +
            """ WHERE ii.id=? AND ii.state='loaded' AND ii.archived_at IS NULL""",
            (instance_id,),
        ).fetchone()
        return dict(row) if row else None

    def _sealed_spool(self, db, instance_id: int) -> dict | None:
        row = db.execute(
            self._spool_select() +
            """ WHERE ii.id=? AND ii.state='sealed' AND ii.archived_at IS NULL
            AND NOT EXISTS (
              SELECT 1 FROM ams_assignments aa
              WHERE aa.instance_id=ii.id AND aa.unloaded_at IS NULL)""",
            (instance_id,),
        ).fetchone()
        return dict(row) if row else None

    def _review_flexible(self, form: dict[str, str]) -> ReplacementReview:
        current_id = self._positive_int(
            form, "current_instance_id", "select the active spool"
        )
        outgoing_disposition = self._choice(
            form, "outgoing_disposition", {"empty", "storage", "ams_slot"}
        )
        incoming_disposition = self._choice(
            form, "incoming_disposition", {"sealed", "open", "none"}
        )
        actor = self._text(form, "actor", 100)
        reason = self._optional(form, "reason", 500)
        print_job_name = self._optional(form, "print_job_name", 160)
        approximate_layer = self._optional_nonnegative_int(
            form, "approximate_layer", "approximate layer"
        )
        printer = self._optional(form, "printer", 120)
        plate = self._optional(form, "plate", 120)
        operational_note = self._optional(form, "operational_note", 1000)

        outgoing_location_id = self._optional_positive_int(
            form, "outgoing_destination_location_id"
        )
        outgoing_slot_id = self._optional_positive_int(
            form, "outgoing_destination_slot_id"
        )
        incoming_id = self._optional_positive_int(form, "incoming_instance_id")
        incoming_source_location_id = self._optional_positive_int(
            form, "incoming_source_location_id"
        )
        incoming_source_slot_id = self._optional_positive_int(
            form, "incoming_source_slot_id"
        )
        incoming_destination_slot_id = self._optional_positive_int(
            form, "incoming_destination_slot_id"
        )
        review_nonce = uuid.uuid4().hex

        db = connect(self.database)
        try:
            current = self._active_spool(db, current_id)
            if not current:
                raise ReplaceSpoolError(
                    "current spool must be actively loaded in an AMS"
                )
            if incoming_disposition != "none" and incoming_destination_slot_id is None:
                incoming_destination_slot_id = current["slot_id"]
            service = InventoryActionService(
                db,
                ActionContext(actor=actor, module=self.MODULE, origin="user"),
            )
            plan = service.preview_flexible_spool_replacement(
                current_id,
                outgoing_disposition=outgoing_disposition,
                outgoing_destination_location_id=outgoing_location_id,
                outgoing_destination_slot_id=outgoing_slot_id,
                incoming_disposition=incoming_disposition,
                incoming_instance_id=incoming_id,
                incoming_source_location_id=incoming_source_location_id,
                incoming_source_slot_id=incoming_source_slot_id,
                incoming_destination_slot_id=incoming_destination_slot_id,
                reason=reason,
                review_nonce=review_nonce,
                print_job_name=print_job_name,
                approximate_layer=approximate_layer,
                printer=printer,
                plate=plate,
                operational_note=operational_note,
            )
            values = {
                "version": 2,
                "reviewed_at": int(time.time()),
                "review_nonce": review_nonce,
                "module": self.MODULE,
                "actor": actor,
                "reason": reason,
                "print_job_name": print_job_name,
                "approximate_layer": approximate_layer,
                "printer": printer,
                "plate": plate,
                "operational_note": operational_note,
                "current_instance_id": current_id,
                "outgoing_disposition": outgoing_disposition,
                "outgoing_destination_location_id": outgoing_location_id,
                "outgoing_destination_slot_id": outgoing_slot_id,
                "incoming_disposition": incoming_disposition,
                "incoming_instance_id": incoming_id,
                "incoming_source_location_id": incoming_source_location_id,
                "incoming_source_slot_id": incoming_source_slot_id,
                "incoming_destination_slot_id": incoming_destination_slot_id,
                "plan": plan,
            }
            return ReplacementReview(self._sign(values), values)
        except InventoryActionError as exc:
            raise ReplaceSpoolError(str(exc)) from exc
        finally:
            db.close()

    def _commit_flexible(self, values: dict) -> dict:
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM inventory_workflow_transactions WHERE review_nonce=?",
                (values["review_nonce"],),
            ).fetchone():
                raise ReplaceSpoolError(
                    "this preview was already used; start a new replacement"
                )
            service = InventoryActionService(
                db,
                ActionContext(
                    actor=values["actor"], module=self.MODULE, origin="user"
                ),
            )
            arguments = self._flexible_arguments(values)
            current_plan = service.preview_flexible_spool_replacement(**arguments)
            if current_plan != values["plan"]:
                raise ReplaceSpoolError(
                    "spool or destination state changed after preview; review again"
                )
            result = service.flexibly_replace_active_filament_spool(**arguments)
            db.commit()
            return {**values, **result}
        except ReplaceSpoolError:
            db.rollback()
            raise
        except (InventoryActionError, sqlite3.IntegrityError) as exc:
            db.rollback()
            message = (
                "this preview was already used; start a new replacement"
                if "review_nonce" in str(exc) or "UNIQUE constraint failed" in str(exc)
                else str(exc)
            )
            raise ReplaceSpoolError(message) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _flexible_arguments(values: dict) -> dict:
        return {
            "current_instance_id": values["current_instance_id"],
            "outgoing_disposition": values["outgoing_disposition"],
            "outgoing_destination_location_id": (
                values["outgoing_destination_location_id"]
            ),
            "outgoing_destination_slot_id": values["outgoing_destination_slot_id"],
            "incoming_disposition": values["incoming_disposition"],
            "incoming_instance_id": values["incoming_instance_id"],
            "incoming_source_location_id": values["incoming_source_location_id"],
            "incoming_source_slot_id": values["incoming_source_slot_id"],
            "incoming_destination_slot_id": values["incoming_destination_slot_id"],
            "reason": values["reason"],
            "review_nonce": values["review_nonce"],
            "print_job_name": values["print_job_name"],
            "approximate_layer": values["approximate_layer"],
            "printer": values["printer"],
            "plate": values["plate"],
            "operational_note": values["operational_note"],
        }

    @staticmethod
    def _spool_select(include_ams: bool = False) -> str:
        fields = (
            ",e.name equipment_name,es.slot_number,es.id slot_id"
            if include_ams else ""
        )
        ams_joins = (
            " JOIN ams_assignments aa ON aa.instance_id=ii.id AND aa.unloaded_at IS NULL"
            " JOIN equipment_slots es ON es.id=aa.slot_id"
            " JOIN equipment e ON e.id=es.equipment_id"
            if include_ams else ""
        )
        return f"""
            SELECT ii.id,ii.permanent_id,ii.state,ii.remaining_quantity,
            m.name manufacturer,ci.product_line,ci.variant color,
            mat.text_value material{fields}
            FROM inventory_instances ii
            JOIN catalog_items ci ON ci.id=ii.catalog_item_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values mat ON mat.catalog_item_id=ci.id
              AND mat.attribute_definition_id=(
                SELECT id FROM attribute_definitions WHERE name='material')
            {ams_joins}"""

    @staticmethod
    def _spool_select_with_optional_ams() -> str:
        return """
            SELECT ii.id,ii.permanent_id,ii.state,ii.remaining_quantity,
            ii.location_id,m.name manufacturer,ci.product_line,ci.variant color,
            mat.text_value material,e.name equipment_name,es.slot_number,
            es.id slot_id
            FROM inventory_instances ii
            JOIN catalog_items ci ON ci.id=ii.catalog_item_id
            JOIN manufacturers m ON m.id=ci.manufacturer_id
            LEFT JOIN catalog_item_attribute_values mat ON mat.catalog_item_id=ci.id
              AND mat.attribute_definition_id=(
                SELECT id FROM attribute_definitions WHERE name='material')
            LEFT JOIN ams_assignments aa
              ON aa.instance_id=ii.id AND aa.unloaded_at IS NULL
            LEFT JOIN equipment_slots es ON es.id=aa.slot_id
            LEFT JOIN equipment e ON e.id=es.equipment_id"""

    @staticmethod
    def _values(db, column: str) -> list[str]:
        allowed = {"m.name", "mat.text_value", "ci.variant"}
        if column not in allowed:
            raise RuntimeError("unsupported replacement facet")
        return [
            row[0] for row in db.execute(
                f"""SELECT DISTINCT {column} FROM inventory_instances ii
                JOIN catalog_items ci ON ci.id=ii.catalog_item_id
                JOIN manufacturers m ON m.id=ci.manufacturer_id
                LEFT JOIN catalog_item_attribute_values mat ON mat.catalog_item_id=ci.id
                  AND mat.attribute_definition_id=(
                    SELECT id FROM attribute_definitions WHERE name='material')
                WHERE ii.state='sealed' AND ii.archived_at IS NULL
                AND {column} IS NOT NULL ORDER BY {column}"""
            )
        ]

    def _sign(self, values: dict) -> str:
        body = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return self._b64(body) + "." + self._b64(signature)

    def _verify(self, token: str) -> dict:
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            signature = self._unb64(signature_text)
            if self._b64(body) != body_text or self._b64(signature) != signature_text:
                raise ValueError
            expected = hmac.new(self.secret, body, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReplaceSpoolError("replacement preview is invalid; start again") from exc
        if values.get("version") not in {1, 2} or values.get("module") != self.MODULE:
            raise ReplaceSpoolError("replacement preview is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise ReplaceSpoolError("replacement preview expired; start again")
        return values

    @staticmethod
    def _text(form: dict[str, str], key: str, limit: int) -> str:
        value = str(form.get(key, "")).strip()
        if not value:
            raise ReplaceSpoolError(f"{key.replace('_', ' ')} is required")
        if len(value) > limit or any(ord(char) < 32 for char in value):
            raise ReplaceSpoolError(f"{key.replace('_', ' ')} is invalid")
        return value

    @classmethod
    def _optional(cls, form: dict[str, str], key: str, limit: int) -> str | None:
        value = str(form.get(key, "")).strip()
        return cls._text(form, key, limit) if value else None

    @staticmethod
    def _positive_int(form: dict[str, str], key: str, message: str) -> int:
        try:
            value = int(form.get(key, ""))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise ReplaceSpoolError(message) from exc

    @staticmethod
    def _optional_positive_int(form: dict[str, str], key: str) -> int | None:
        raw = str(form.get(key, "")).strip()
        if not raw:
            return None
        try:
            value = int(raw)
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise ReplaceSpoolError(f"{key.replace('_', ' ')} is invalid") from exc

    @staticmethod
    def _choice(form: dict[str, str], key: str, allowed: set[str]) -> str:
        value = str(form.get(key, "")).strip()
        if value not in allowed:
            raise ReplaceSpoolError(f"select a valid {key.replace('_', ' ')}")
        return value

    @staticmethod
    def _optional_nonnegative_int(
        form: dict[str, str], key: str, label: str
    ) -> int | None:
        raw = str(form.get(key, "")).strip()
        if not raw:
            return None
        try:
            value = int(raw)
            if value < 0:
                raise ValueError
            return value
        except ValueError as exc:
            raise ReplaceSpoolError(f"{label} must be a whole number or blank") from exc

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

