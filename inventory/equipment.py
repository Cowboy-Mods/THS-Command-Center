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
from pathlib import Path
from typing import Protocol

from .db import connect


class EquipmentError(ValueError):
    """An equipment preview or commit is invalid, stale, or already used."""


class BambuPrinterIntegrationService(Protocol):
    """Future telemetry adapter seam; it cannot mutate authoritative domains."""

    def observe(self, equipment_id: int) -> dict:
        """Return a non-authoritative, freshness-stamped device observation."""


class CameraViewingGateway(Protocol):
    """Future authenticated, short-lived camera-viewing seam."""

    def create_viewing_session(self, equipment_id: int, capability_code: str) -> dict:
        """Return an ephemeral session without persisting credentials in equipment."""


class PrintJobCorrelator(Protocol):
    """Future seam for proposing, not committing, production-record correlations."""

    def completion_candidate(self, equipment_id: int, observation: dict) -> dict:
        """Return an idempotent candidate for a separate production workflow."""


class EquipmentRegistryService:
    MODULE = "equipment-registry"
    MAX_REVIEW_AGE_SECONDS = 30 * 60
    LIFECYCLE_STATES = {
        "registered", "installed", "commissioned", "decommissioned",
        "retired", "disposed",
    }
    OPERATIONAL_STATUSES = {
        "unknown", "offline", "idle", "operating", "standby",
        "degraded", "faulted", "maintenance",
    }
    RELATIONSHIP_TYPES = {"attached_to", "installed_in", "managed_by"}
    CAPABILITY_SUPPORT = {"supported", "unsupported", "unknown"}
    CAPABILITY_SOURCES = {
        "manufacturer_specification", "physical_verification",
        "manual_configuration", "integration_discovery",
    }

    def __init__(self, database, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def review_register(self, form: dict) -> dict:
        actor = self._text(form.get("actor"), "actor", 100)
        reason = self._optional_text(form.get("reason"), 2000)
        display_name = self._text(form.get("display_name"), "display name", 200)
        type_code = self._text(form.get("type_code"), "equipment type", 80)
        subtype_code = self._optional_text(form.get("subtype_code"), 80)
        manufacturer_id = self._optional_int(form.get("manufacturer_id"), "manufacturer")
        location_id = self._optional_int(form.get("current_location_id"), "location")
        lifecycle = self._text(
            form.get("lifecycle_state", "registered"), "lifecycle state", 40
        )
        operational = self._text(
            form.get("operational_status", "unknown"), "operational status", 40
        )
        if lifecycle not in self.LIFECYCLE_STATES:
            raise EquipmentError("select a valid equipment lifecycle state")
        if operational not in self.OPERATIONAL_STATUSES:
            raise EquipmentError("select a valid equipment operational status")
        with closing(connect(self.database)) as db:
            equipment_type = db.execute(
                "SELECT * FROM equipment_types WHERE type_code=? AND active=1",
                (type_code,),
            ).fetchone()
            if not equipment_type:
                raise EquipmentError("equipment type is unavailable")
            subtype = None
            if subtype_code:
                subtype = db.execute(
                    """SELECT * FROM equipment_subtypes
                    WHERE subtype_code=? AND equipment_type_id=? AND active=1""",
                    (subtype_code, equipment_type["id"]),
                ).fetchone()
                if not subtype:
                    raise EquipmentError("equipment subtype does not belong to equipment type")
            manufacturer = self._foreign_snapshot(
                db, "manufacturers", manufacturer_id, "manufacturer"
            )
            location = self._foreign_snapshot(db, "locations", location_id, "location")
            duplicate = db.execute(
                "SELECT equipment_number FROM equipment_registry WHERE lower(trim(display_name))=lower(trim(?))",
                (display_name,),
            ).fetchone()
            if duplicate:
                raise EquipmentError("equipment display name is already registered")
            equipment_number = self._next_equipment_number(db)
            capability_rows = self._capability_values(
                db, form.get("capabilities", []), type_code
            )
        values = {
            "version": 1,
            "action": "register",
            "reviewed_at": int(time.time()),
            "request_nonce": uuid.uuid4().hex,
            "equipment_uuid": str(uuid.uuid4()),
            "equipment_number": equipment_number,
            "history_uuid": str(uuid.uuid4()),
            "audit_uuid": str(uuid.uuid4()),
            "actor": actor,
            "reason": reason,
            "display_name": display_name,
            "equipment_type": dict(equipment_type),
            "equipment_subtype": dict(subtype) if subtype else None,
            "manufacturer": dict(manufacturer) if manufacturer else None,
            "model": self._optional_text(form.get("model"), 200),
            "manufacturer_serial_number": self._optional_text(
                form.get("manufacturer_serial_number"), 300
            ),
            "ths_asset_identifier": self._optional_text(
                form.get("ths_asset_identifier"), 300
            ),
            "location": dict(location) if location else None,
            "lifecycle_state": lifecycle,
            "operational_status": operational,
            "installed_at": self._optional_text(form.get("installed_at"), 50),
            "commissioned_at": self._optional_text(form.get("commissioned_at"), 50),
            "retired_at": self._optional_text(form.get("retired_at"), 50),
            "disposed_at": self._optional_text(form.get("disposed_at"), 50),
            "notes": self._optional_text(form.get("notes"), 4000),
            "capabilities": capability_rows,
        }
        self._validate_lifecycle_dates(values)
        return {"token": self._sign(values), "values": values}

    def commit_register(self, token: str, *, confirmed: bool) -> dict:
        if not confirmed:
            raise EquipmentError("explicit equipment registration confirmation is required")
        values = self._verify(token, "register")
        with closing(connect(self.database)) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if self._nonce_used(db, values["request_nonce"]):
                    raise EquipmentError("this equipment preview was already used")
                if self._next_equipment_number(db) != values["equipment_number"]:
                    raise EquipmentError(
                        "equipment sequence changed after preview; review again"
                    )
                self._revalidate_registration(db, values)
                equipment_id = db.execute(
                    """INSERT INTO equipment_registry(
                    equipment_uuid,equipment_number,display_name,equipment_type_id,
                    equipment_subtype_id,manufacturer_id,model,
                    manufacturer_serial_number,ths_asset_identifier,current_location_id,
                    lifecycle_state,operational_status,installed_at,commissioned_at,
                    retired_at,disposed_at,notes,created_by)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        values["equipment_uuid"], values["equipment_number"],
                        values["display_name"], values["equipment_type"]["id"],
                        self._id(values["equipment_subtype"]),
                        self._id(values["manufacturer"]), values["model"],
                        values["manufacturer_serial_number"],
                        values["ths_asset_identifier"], self._id(values["location"]),
                        values["lifecycle_state"], values["operational_status"],
                        values["installed_at"], values["commissioned_at"],
                        values["retired_at"], values["disposed_at"], values["notes"],
                        values["actor"],
                    ),
                ).lastrowid
                for capability in values["capabilities"]:
                    db.execute(
                        """INSERT INTO equipment_capabilities(
                        capability_uuid,equipment_id,capability_type_id,support_state,
                        source,configuration_metadata,verified_at,verified_by)
                        VALUES (?,?,?,?,?,?,?,?)""",
                        (
                            capability["capability_uuid"], equipment_id,
                            capability["capability_type_id"],
                            capability["support_state"], capability["source"],
                            capability["configuration_metadata"],
                            capability["verified_at"], values["actor"],
                        ),
                    )
                    if capability["capability_code"] == "camera.builtin":
                        db.execute(
                            """INSERT INTO equipment_component_installations(
                            installation_uuid,host_equipment_id,component_role,embedded,
                            independently_tracked,installed_at,installed_by,notes)
                            VALUES (?,?,?,1,0,?,?,?)""",
                            (
                                capability["installation_uuid"], equipment_id,
                                "built_in_camera",
                                values["installed_at"] or values["reviewed_at_iso"],
                                values["actor"],
                                "Factory-integrated capability; no separate THS-EQP identity.",
                            ),
                        )
                snapshot = self._registration_snapshot(values, equipment_id)
                db.execute(
                    """INSERT INTO equipment_history(
                    history_uuid,request_nonce,equipment_id,action_type,
                    previous_state_version,new_state_version,snapshot,actor,reason)
                    VALUES (?,?,?,'register',NULL,1,?,?,?)""",
                    (
                        values["history_uuid"], values["request_nonce"], equipment_id,
                        self._json(snapshot), values["actor"], values["reason"],
                    ),
                )
                self._audit(db, values, equipment_id, "register_equipment")
                db.commit()
                return {
                    "id": equipment_id,
                    "equipment_number": values["equipment_number"],
                    "equipment_uuid": values["equipment_uuid"],
                }
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise EquipmentError(f"equipment registration conflicts with current data: {exc}") from exc
            except Exception:
                db.rollback()
                raise

    def review_relationship(self, form: dict) -> dict:
        actor = self._text(form.get("actor"), "actor", 100)
        action = self._text(form.get("action"), "relationship action", 20)
        if action not in {"attach", "move", "detach"}:
            raise EquipmentError("relationship action must be attach, move, or detach")
        child_id = self._optional_int(form.get("child_equipment_id"), "child equipment")
        parent_id = self._optional_int(form.get("parent_equipment_id"), "parent equipment")
        relationship_type = self._optional_text(form.get("relationship_type"), 40)
        effective_at = self._text(form.get("effective_at"), "effective time", 50)
        with closing(connect(self.database)) as db:
            child = self._equipment_snapshot(db, child_id)
            current_row = db.execute(
                """SELECT ers.*,p.equipment_number parent_equipment_number,
                p.display_name parent_name
                FROM equipment_relationship_state ers
                JOIN equipment_registry p ON p.id=ers.parent_equipment_id
                WHERE ers.child_equipment_id=?""",
                (child_id,),
            ).fetchone()
            current = dict(current_row) if current_row else None
            parent = None
            if action != "detach":
                if not parent_id or parent_id == child_id:
                    raise EquipmentError("select a different parent equipment record")
                parent = self._equipment_snapshot(db, parent_id)
                if relationship_type not in self.RELATIONSHIP_TYPES:
                    raise EquipmentError("select a valid relationship type")
                self._reject_cycle(db, child_id, parent_id)
            if action == "attach" and current:
                raise EquipmentError("child already has a parent; use move")
            if action == "move" and not current:
                raise EquipmentError("child has no current parent; use attach")
            if action == "detach" and not current:
                raise EquipmentError("child has no current parent to detach")
            if current and parent_id == current["parent_equipment_id"]:
                raise EquipmentError("new parent duplicates the current parent")
        next_version = (current["state_version"] if current else 0) + 1
        values = {
            "version": 1,
            "action": f"relationship_{action}",
            "relationship_action": action,
            "reviewed_at": int(time.time()),
            "request_nonce": uuid.uuid4().hex,
            "history_uuid": str(uuid.uuid4()),
            "audit_uuid": str(uuid.uuid4()),
            "actor": actor,
            "reason": self._optional_text(form.get("reason"), 2000),
            "effective_at": effective_at,
            "child": child,
            "current": current,
            "new_parent": parent,
            "new_relationship_type": relationship_type if action != "detach" else None,
            "new_state_version": next_version,
        }
        return {"token": self._sign(values), "values": values}

    def commit_relationship(self, token: str, *, confirmed: bool) -> dict:
        if not confirmed:
            raise EquipmentError("explicit relationship confirmation is required")
        values = self._verify(token)
        if not values["action"].startswith("relationship_"):
            raise EquipmentError("equipment preview action does not match relationship")
        with closing(connect(self.database)) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if self._nonce_used(db, values["request_nonce"]):
                    raise EquipmentError("this relationship preview was already used")
                child = self._equipment_snapshot(db, values["child"]["id"])
                if child != values["child"]:
                    raise EquipmentError("child equipment changed after preview")
                current_row = db.execute(
                    """SELECT ers.*,p.equipment_number parent_equipment_number,
                    p.display_name parent_name
                    FROM equipment_relationship_state ers
                    JOIN equipment_registry p ON p.id=ers.parent_equipment_id
                    WHERE ers.child_equipment_id=?""",
                    (child["id"],),
                ).fetchone()
                current = dict(current_row) if current_row else None
                if current != values["current"]:
                    raise EquipmentError("equipment relationship changed after preview")
                new_parent = values["new_parent"]
                if new_parent:
                    if self._equipment_snapshot(db, new_parent["id"]) != new_parent:
                        raise EquipmentError("parent equipment changed after preview")
                    self._reject_cycle(db, child["id"], new_parent["id"])
                action = values["relationship_action"]
                if action == "detach":
                    db.execute(
                        "DELETE FROM equipment_relationship_state WHERE child_equipment_id=?",
                        (child["id"],),
                    )
                elif current:
                    db.execute(
                        """UPDATE equipment_relationship_state SET
                        parent_equipment_id=?,relationship_type=?,state_version=?,
                        effective_at=?,updated_at=CURRENT_TIMESTAMP
                        WHERE child_equipment_id=? AND state_version=?""",
                        (
                            new_parent["id"], values["new_relationship_type"],
                            values["new_state_version"], values["effective_at"],
                            child["id"], current["state_version"],
                        ),
                    )
                    if db.total_changes != 1:
                        raise EquipmentError("relationship state is stale")
                else:
                    db.execute(
                        """INSERT INTO equipment_relationship_state(
                        child_equipment_id,parent_equipment_id,relationship_type,
                        state_version,effective_at) VALUES (?,?,?,?,?)""",
                        (
                            child["id"], new_parent["id"],
                            values["new_relationship_type"],
                            values["new_state_version"], values["effective_at"],
                        ),
                    )
                snapshot = {
                    "child": child, "previous": current, "new_parent": new_parent,
                    "new_relationship_type": values["new_relationship_type"],
                }
                db.execute(
                    """INSERT INTO equipment_relationship_history(
                    history_uuid,request_nonce,child_equipment_id,
                    previous_parent_equipment_id,new_parent_equipment_id,
                    previous_relationship_type,new_relationship_type,action_type,
                    previous_state_version,new_state_version,effective_at,actor,reason,snapshot)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        values["history_uuid"], values["request_nonce"], child["id"],
                        current["parent_equipment_id"] if current else None,
                        new_parent["id"] if new_parent else None,
                        current["relationship_type"] if current else None,
                        values["new_relationship_type"], action,
                        current["state_version"] if current else None,
                        values["new_state_version"], values["effective_at"],
                        values["actor"], values["reason"], self._json(snapshot),
                    ),
                )
                self._audit(db, values, child["id"], f"{action}_equipment_relationship")
                db.commit()
                return {
                    "child_equipment_id": child["id"],
                    "action": action,
                    "state_version": values["new_state_version"],
                }
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise EquipmentError(f"equipment relationship conflicts with current data: {exc}") from exc
            except Exception:
                db.rollback()
                raise

    def _capability_values(self, db, raw, type_code):
        if isinstance(raw, str):
            raw = [item.strip() for item in raw.split(",") if item.strip()]
        if not isinstance(raw, list):
            raise EquipmentError("capabilities must be a list")
        result = []
        seen = set()
        for item in raw:
            if isinstance(item, str):
                item = {"capability_code": item}
            code = self._text(item.get("capability_code"), "capability code", 100)
            if code in seen:
                raise EquipmentError("duplicate equipment capability")
            seen.add(code)
            row = db.execute(
                "SELECT * FROM equipment_capability_types WHERE capability_code=?",
                (code,),
            ).fetchone()
            if not row:
                raise EquipmentError("equipment capability is unavailable")
            if code == "camera.builtin" and type_code != "printer":
                raise EquipmentError("built-in camera capability belongs to a printer")
            support = item.get("support_state", "supported")
            source = item.get("source", "manufacturer_specification")
            if support not in self.CAPABILITY_SUPPORT or source not in self.CAPABILITY_SOURCES:
                raise EquipmentError("invalid capability support or source")
            metadata = item.get("configuration_metadata")
            if metadata is not None:
                metadata = self._json(metadata)
                if any(word in metadata.casefold() for word in (
                    "password", "token", "secret", "credential"
                )):
                    raise EquipmentError("capability metadata cannot contain credentials")
            result.append({
                "capability_uuid": str(uuid.uuid4()),
                "installation_uuid": str(uuid.uuid4()),
                "capability_type_id": row["id"],
                "capability_code": code,
                "support_state": support,
                "source": source,
                "configuration_metadata": metadata,
                "verified_at": item.get("verified_at"),
            })
        return result

    def _revalidate_registration(self, db, values):
        if db.execute(
            "SELECT 1 FROM equipment_registry WHERE lower(trim(display_name))=lower(trim(?))",
            (values["display_name"],),
        ).fetchone():
            raise EquipmentError("equipment display name was registered after preview")
        equipment_type = db.execute(
            "SELECT * FROM equipment_types WHERE id=? AND active=1",
            (values["equipment_type"]["id"],),
        ).fetchone()
        if not equipment_type or dict(equipment_type) != values["equipment_type"]:
            raise EquipmentError("equipment type changed after preview")
        for key, table in (
            ("manufacturer", "manufacturers"),
            ("location", "locations"),
            ("equipment_subtype", "equipment_subtypes"),
        ):
            expected = values[key]
            if expected:
                row = db.execute(f"SELECT * FROM {table} WHERE id=?", (expected["id"],)).fetchone()
                if not row or dict(row) != expected:
                    raise EquipmentError(f"{key.replace('_', ' ')} changed after preview")

    def _reject_cycle(self, db, child_id, parent_id):
        if db.execute(
            """WITH RECURSIVE ancestors(id) AS (
              SELECT parent_equipment_id FROM equipment_relationship_state
              WHERE child_equipment_id=?
              UNION ALL
              SELECT ers.parent_equipment_id
              FROM equipment_relationship_state ers JOIN ancestors a
                ON ers.child_equipment_id=a.id
            ) SELECT 1 FROM ancestors WHERE id=? LIMIT 1""",
            (parent_id, child_id),
        ).fetchone():
            raise EquipmentError("equipment relationship would create a cycle")

    def _equipment_snapshot(self, db, equipment_id):
        row = db.execute(
            """SELECT id,equipment_uuid,equipment_number,display_name,
            equipment_type_id,equipment_subtype_id,lifecycle_state,
            operational_status,current_location_id,state_version,updated_at
            FROM equipment_registry WHERE id=?""", (equipment_id,)
        ).fetchone()
        if not row:
            raise EquipmentError("equipment record not found")
        if row["lifecycle_state"] == "disposed":
            raise EquipmentError("disposed equipment cannot change relationships")
        return dict(row)

    def _next_equipment_number(self, db):
        maximum = 0
        for row in db.execute("SELECT equipment_number FROM equipment_registry"):
            try:
                maximum = max(maximum, int(row[0].removeprefix("THS-EQP-")))
            except ValueError:
                raise EquipmentError("existing equipment number sequence is invalid")
        return f"THS-EQP-{maximum + 1:06d}"

    def _nonce_used(self, db, nonce):
        return bool(
            db.execute("SELECT 1 FROM equipment_history WHERE request_nonce=?", (nonce,)).fetchone()
            or db.execute(
                "SELECT 1 FROM equipment_relationship_history WHERE request_nonce=?", (nonce,)
            ).fetchone()
            or db.execute("SELECT 1 FROM audit_events WHERE request_nonce=?", (nonce,)).fetchone()
        )

    def _audit(self, db, values, equipment_id, event_type):
        db.execute(
            """INSERT INTO audit_events(
            event_uuid,actor,module,origin,event_type,entity_type,entity_id,
            entity_human_id,summary,details,request_nonce)
            VALUES (?,?,'equipment-registry','user',?,'equipment',?,?,?,?,?)""",
            (
                values["audit_uuid"], values["actor"], event_type, equipment_id,
                values.get("equipment_number") or values["child"]["equipment_number"],
                event_type.replace("_", " ").title(),
                self._json({"reason": values.get("reason"), "action": values["action"]}),
                values["request_nonce"],
            ),
        )

    def _registration_snapshot(self, values, equipment_id):
        return {
            "equipment_id": equipment_id,
            "equipment_uuid": values["equipment_uuid"],
            "equipment_number": values["equipment_number"],
            "display_name": values["display_name"],
            "equipment_type": values["equipment_type"],
            "equipment_subtype": values["equipment_subtype"],
            "manufacturer": values["manufacturer"],
            "model": values["model"],
            "manufacturer_serial_number": values["manufacturer_serial_number"],
            "ths_asset_identifier": values["ths_asset_identifier"],
            "location": values["location"],
            "lifecycle_state": values["lifecycle_state"],
            "operational_status": values["operational_status"],
            "capabilities": values["capabilities"],
        }

    def _validate_lifecycle_dates(self, values):
        lifecycle = values["lifecycle_state"]
        if lifecycle in {"commissioned", "decommissioned"} and not values["commissioned_at"]:
            raise EquipmentError("commissioned lifecycle requires commissioning time")
        if lifecycle in {"retired", "disposed"} and not values["retired_at"]:
            raise EquipmentError("retired lifecycle requires retirement time")
        if lifecycle == "disposed" and not values["disposed_at"]:
            raise EquipmentError("disposed lifecycle requires disposal time")

    def _foreign_snapshot(self, db, table, row_id, label):
        if row_id is None:
            return None
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        if not row:
            raise EquipmentError(f"{label} not found")
        return row

    def _sign(self, values):
        values = dict(values)
        values["reviewed_at_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(values["reviewed_at"])
        )
        body = self._json(values).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return f"{self._b64(body)}.{self._b64(signature)}"

    def _verify(self, token, expected_action=None):
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            signature = self._unb64(signature_text)
            if self._b64(body) != body_text or not hmac.compare_digest(
                signature, hmac.new(self.secret, body, hashlib.sha256).digest()
            ):
                raise EquipmentError("equipment preview signature is invalid")
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise EquipmentError("equipment preview signature is invalid") from exc
        age = time.time() - values.get("reviewed_at", 0)
        if age < -60 or age > self.MAX_REVIEW_AGE_SECONDS:
            raise EquipmentError("equipment preview expired; review again")
        if expected_action and values.get("action") != expected_action:
            raise EquipmentError("equipment preview action does not match")
        return values

    @staticmethod
    def _id(value):
        return value["id"] if value else None

    @staticmethod
    def _text(value, label, maximum):
        value = str(value or "").strip()
        if not value:
            raise EquipmentError(f"{label} is required")
        if len(value) > maximum:
            raise EquipmentError(f"{label} is too long")
        return value

    @staticmethod
    def _optional_text(value, maximum):
        value = str(value or "").strip()
        if not value:
            return None
        if len(value) > maximum:
            raise EquipmentError("equipment value is too long")
        return value

    @staticmethod
    def _optional_int(value, label):
        if value in (None, ""):
            return None
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise EquipmentError(f"{label} must be a positive number") from exc
        if value <= 0:
            raise EquipmentError(f"{label} must be a positive number")
        return value

    @staticmethod
    def _json(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    @staticmethod
    def _unb64(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
