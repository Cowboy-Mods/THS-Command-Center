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
from datetime import datetime
from pathlib import Path

from .db import connect


class MaintenanceError(ValueError):
    """A maintenance preview or state transition is invalid."""


class MaintenanceWorkflow:
    MODULE = "maintenance-registry"
    MAX_REVIEW_AGE_SECONDS = 30 * 60
    EVENT_TYPES = {
        "inspection", "cleaning", "repair", "preventive_maintenance",
        "fault_discovered", "part_replacement",
    }
    STATUSES = {
        "pending", "in_progress", "blocked_waiting_for_part", "completed", "verified",
    }
    SEVERITIES = {"informational", "low", "medium", "high", "printer_unsafe"}
    READINESS = {
        "normal", "monitor_during_printing", "no_unattended_printing", "out_of_service",
    }
    ACTION_TARGETS = {
        "record_fault": (None, "pending"),
        "create_task": (None, "pending"),
        "mark_waiting_for_part": ({"pending", "in_progress"}, "blocked_waiting_for_part"),
        "complete_maintenance": (
            {"pending", "in_progress", "blocked_waiting_for_part"}, "completed"
        ),
        "verify_repair": ({"completed"}, "verified"),
        "reopen_task": ({"completed", "verified"}, "pending"),
    }

    def __init__(self, database, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def options(self) -> dict:
        with closing(connect(self.database)) as db:
            return {
                "assets": [dict(r) for r in db.execute(
                    "SELECT * FROM maintenance_assets ORDER BY display_name"
                )],
                "prints": [dict(r) for r in db.execute(
                    "SELECT id,print_number,part_name FROM print_records ORDER BY id DESC"
                )],
            }

    def review(self, action: str, form: dict[str, str]) -> dict:
        if action not in self.ACTION_TARGETS:
            raise MaintenanceError("unsupported maintenance workflow")
        actor = self._text(form, "actor", 100)
        with closing(connect(self.database)) as db:
            values = {
                "version": 1, "module": self.MODULE, "action": action,
                "reviewed_at": int(time.time()), "request_nonce": uuid.uuid4().hex,
                "actor": actor,
            }
            if action in {"record_fault", "create_task"}:
                values.update(self._review_new(db, action, form))
            else:
                values.update(self._review_transition(db, action, form))
        return {"token": self._sign(values), "values": values}

    def commit(self, token: str) -> dict:
        values = self._verify(token)
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM maintenance_history WHERE request_nonce=?",
                (values["request_nonce"],),
            ).fetchone():
                raise MaintenanceError("this maintenance preview was already used")
            if values["action"] in {"record_fault", "create_task"}:
                result = self._commit_new(db, values)
            else:
                result = self._commit_transition(db, values)
            db.commit()
            return result
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise MaintenanceError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add_evidence(
        self, record_id: int, *, evidence_type: str, file_path: str,
        actor: str, sha256: str | None = None, caption: str | None = None,
        captured_at: str | None = None,
    ) -> dict:
        if evidence_type not in {"photo", "video"}:
            raise MaintenanceError("evidence must be a photo or video")
        actor = self._value(actor, "actor", 100)
        path = Path(self._value(file_path, "evidence file path", 2000))
        if not path.is_absolute():
            raise MaintenanceError("evidence file path must be absolute")
        if sha256 is None:
            if not path.is_file():
                raise MaintenanceError("evidence file does not exist")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            sha256 = digest.hexdigest()
        sha256 = sha256.lower()
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise MaintenanceError("evidence SHA-256 must contain 64 hexadecimal characters")
        if captured_at:
            self._timestamp(captured_at, "capture time")
        with closing(connect(self.database)) as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute(
                "SELECT event_number FROM maintenance_records WHERE id=?", (record_id,)
            ).fetchone()
            if not record:
                raise MaintenanceError("maintenance record not found")
            evidence_id = db.execute(
                """INSERT INTO maintenance_evidence(
                evidence_uuid,maintenance_record_id,evidence_type,file_path,sha256,
                caption,captured_at,added_by) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), record_id, evidence_type, str(path), sha256,
                    self._optional_value(caption, 1000), captured_at, actor,
                ),
            ).lastrowid
            db.commit()
            return {"id": evidence_id, "event_number": record["event_number"], "sha256": sha256}

    @staticmethod
    def backlog(database) -> dict:
        with closing(connect(database)) as db:
            rows = [dict(r) for r in db.execute(
                """SELECT mr.*,ma.display_name,ma.readiness_state,pr.print_number,
                (SELECT COUNT(*) FROM maintenance_evidence me
                  WHERE me.maintenance_record_id=mr.id) evidence_count
                FROM maintenance_records mr JOIN maintenance_assets ma ON ma.id=mr.asset_id
                LEFT JOIN print_records pr ON pr.id=mr.related_print_id
                ORDER BY mr.discovered_at DESC,mr.id DESC"""
            )]
            assets = [dict(r) for r in db.execute(
                "SELECT display_name,asset_type,readiness_state FROM maintenance_assets "
                "ORDER BY display_name"
            )]
        now = datetime.now().astimezone()
        def overdue(row):
            if not row["due_at"] or row["status"] in {"completed", "verified"}:
                return False
            return datetime.fromisoformat(row["due_at"]).astimezone() < now
        return {
            "open": [r for r in rows if r["status"] in {"pending", "in_progress"}],
            "blocked": [r for r in rows if r["status"] == "blocked_waiting_for_part"],
            "overdue": [r for r in rows if overdue(r)],
            "completed": [r for r in rows if r["status"] in {"completed", "verified"}],
            "assets": assets,
        }

    def _review_new(self, db, action, form):
        asset_id = self._positive_int(form, "asset_id", "select equipment")
        asset = db.execute(
            "SELECT * FROM maintenance_assets WHERE id=?", (asset_id,)
        ).fetchone()
        if not asset:
            raise MaintenanceError("selected equipment is unavailable")
        event_type = self._text(form, "event_type", 40)
        severity = self._text(form, "severity", 40)
        readiness = self._text(form, "readiness_state", 40)
        if event_type not in self.EVENT_TYPES:
            raise MaintenanceError("select a valid maintenance event type")
        if action == "record_fault" and event_type != "fault_discovered":
            raise MaintenanceError("Record Fault Discovered requires fault discovered event type")
        if severity not in self.SEVERITIES or readiness not in self.READINESS:
            raise MaintenanceError("select valid severity and equipment readiness")
        discovered_at = self._text(form, "discovered_at", 50)
        self._timestamp(discovered_at, "discovered time")
        due_at = self._optional(form, "due_at", 50)
        if due_at:
            self._timestamp(due_at, "due time")
        related_print_id = self._optional_positive_int(form, "related_print_id")
        if related_print_id and not db.execute(
            "SELECT 1 FROM print_records WHERE id=?", (related_print_id,)
        ).fetchone():
            raise MaintenanceError("related print record not found")
        symptoms = self._text(form, "symptoms", 4000)
        parts_required = self._optional(form, "parts_required", 2000)
        return {
            "record_id": None, "asset_id": asset_id, "asset_name": asset["display_name"],
            "asset_readiness_before": asset["readiness_state"],
            "event_number": self._next_number(db), "event_type": event_type,
            "status": "pending", "severity": severity, "discovered_at": discovered_at,
            "due_at": due_at, "symptoms": symptoms,
            "likely_cause": self._optional(form, "likely_cause", 4000),
            "corrective_action": self._optional(form, "corrective_action", 4000),
            "parts_required": parts_required,
            "parts_used": self._optional(form, "parts_used", 2000),
            "notes": self._optional(form, "notes", 4000),
            "related_print_id": related_print_id,
            "unattended_printing_allowed": self._bool(form, "unattended_printing_allowed"),
            "readiness_state": readiness,
        }

    def _review_transition(self, db, action, form):
        record_id = self._positive_int(form, "record_id", "select a maintenance record")
        record = db.execute(
            """SELECT mr.*,ma.display_name,ma.readiness_state FROM maintenance_records mr
            JOIN maintenance_assets ma ON ma.id=mr.asset_id WHERE mr.id=?""", (record_id,)
        ).fetchone()
        if not record:
            raise MaintenanceError("maintenance record not found")
        allowed, new_status = self.ACTION_TARGETS[action]
        if record["status"] not in allowed:
            raise MaintenanceError(
                f"{action.replace('_', ' ')} is not allowed from {record['status'].replace('_', ' ')}"
            )
        readiness = self._text(form, "readiness_state", 40)
        if readiness not in self.READINESS:
            raise MaintenanceError("select valid equipment readiness")
        parts_required = self._optional(form, "parts_required", 2000)
        if action == "mark_waiting_for_part" and not (parts_required or record["parts_required"]):
            raise MaintenanceError("waiting for part requires the missing or required part")
        completed_at = None
        if action in {"complete_maintenance", "verify_repair"}:
            completed_at = self._text(form, "completed_at", 50)
            self._timestamp(completed_at, "completion time")
        return {
            "record_id": record_id, "event_number": record["event_number"],
            "asset_id": record["asset_id"], "asset_name": record["display_name"],
            "previous_status": record["status"], "status": new_status,
            "asset_readiness_before": record["readiness_state"],
            "readiness_state": readiness,
            "unattended_printing_allowed": self._bool(form, "unattended_printing_allowed"),
            "reason": self._text(form, "reason", 4000),
            "parts_required": parts_required,
            "parts_used": self._optional(form, "parts_used", 2000),
            "corrective_action": self._optional(form, "corrective_action", 4000),
            "completed_at": completed_at,
        }

    def _commit_new(self, db, values):
        if self._next_number(db) != values["event_number"]:
            raise MaintenanceError("maintenance registry changed after preview; review again")
        current = db.execute(
            "SELECT readiness_state FROM maintenance_assets WHERE id=?", (values["asset_id"],)
        ).fetchone()
        if not current or current["readiness_state"] != values["asset_readiness_before"]:
            raise MaintenanceError("equipment readiness changed after preview; review again")
        record_id = db.execute(
            """INSERT INTO maintenance_records(
            event_number,asset_id,event_type,status,severity,discovered_at,due_at,symptoms,
            likely_cause,corrective_action,parts_required,parts_used,notes,related_print_id,
            unattended_printing_allowed,created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                values["event_number"], values["asset_id"], values["event_type"],
                values["status"], values["severity"], values["discovered_at"], values["due_at"],
                values["symptoms"], values["likely_cause"], values["corrective_action"],
                values["parts_required"], values["parts_used"], values["notes"],
                values["related_print_id"], int(values["unattended_printing_allowed"]),
                values["actor"],
            ),
        ).lastrowid
        self._set_readiness(db, values["asset_id"], values["readiness_state"])
        history_id = self._history(db, values, record_id, None)
        return {**values, "record_id": record_id, "history_id": history_id}

    def _commit_transition(self, db, values):
        record = db.execute(
            """SELECT mr.status,ma.readiness_state FROM maintenance_records mr
            JOIN maintenance_assets ma ON ma.id=mr.asset_id WHERE mr.id=?""",
            (values["record_id"],),
        ).fetchone()
        if (
            not record or record["status"] != values["previous_status"]
            or record["readiness_state"] != values["asset_readiness_before"]
        ):
            raise MaintenanceError("maintenance state changed after preview; review again")
        fields = [
            "status=?", "unattended_printing_allowed=?", "updated_at=CURRENT_TIMESTAMP"
        ]
        params = [values["status"], int(values["unattended_printing_allowed"])]
        for name in ("parts_required", "parts_used", "corrective_action"):
            if values.get(name):
                fields.append(f"{name}=?")
                params.append(values[name])
        if values.get("completed_at"):
            fields.append("completed_at=?")
            params.append(values["completed_at"])
        elif values["action"] == "reopen_task":
            fields.append("completed_at=NULL")
        params.append(values["record_id"])
        db.execute(f"UPDATE maintenance_records SET {','.join(fields)} WHERE id=?", params)
        self._set_readiness(db, values["asset_id"], values["readiness_state"])
        history_id = self._history(
            db, values, values["record_id"], values["previous_status"]
        )
        return {**values, "history_id": history_id}

    def _history(self, db, values, record_id, previous_status):
        snapshot = dict(db.execute(
            "SELECT * FROM maintenance_records WHERE id=?", (record_id,)
        ).fetchone())
        return db.execute(
            """INSERT INTO maintenance_history(
            history_uuid,request_nonce,maintenance_record_id,action_type,previous_status,
            new_status,previous_readiness_state,new_readiness_state,snapshot,reason,actor)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), values["request_nonce"], record_id, values["action"],
                previous_status, values["status"], values["asset_readiness_before"],
                values["readiness_state"], json.dumps(snapshot, sort_keys=True),
                values.get("reason"), values["actor"],
            ),
        ).lastrowid

    @staticmethod
    def _set_readiness(db, asset_id, readiness):
        db.execute(
            "UPDATE maintenance_assets SET readiness_state=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (readiness, asset_id),
        )

    @staticmethod
    def _next_number(db):
        maximum = db.execute(
            """SELECT MAX(CAST(SUBSTR(event_number,LENGTH('THS-MNT')+2) AS INTEGER))
            FROM (
              SELECT event_number FROM maintenance_events
              UNION ALL SELECT event_number FROM maintenance_records
            ) WHERE event_number LIKE 'THS-MNT-%'"""
        ).fetchone()[0] or 0
        return f"THS-MNT-{maximum + 1:06d}"

    def _sign(self, values):
        body = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return self._b64(body) + "." + self._b64(signature)

    def _verify(self, token):
        try:
            body_text, signature_text = token.split(".", 1)
            body = self._unb64(body_text)
            signature = self._unb64(signature_text)
            if not hmac.compare_digest(
                signature, hmac.new(self.secret, body, hashlib.sha256).digest()
            ):
                raise ValueError
            values = json.loads(body)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MaintenanceError("maintenance preview is invalid; start again") from exc
        if values.get("version") != 1 or values.get("module") != self.MODULE:
            raise MaintenanceError("maintenance preview is invalid; start again")
        if time.time() - values.get("reviewed_at", 0) > self.MAX_REVIEW_AGE_SECONDS:
            raise MaintenanceError("maintenance preview expired; start again")
        return values

    @staticmethod
    def _timestamp(value, label):
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise MaintenanceError(f"{label} must be valid RFC3339") from exc
        if parsed.tzinfo is None:
            raise MaintenanceError(f"{label} must include a UTC offset")

    @staticmethod
    def _value(value, label, limit):
        value = str(value or "").strip()
        if not value or len(value) > limit or any(ord(c) < 32 for c in value):
            raise MaintenanceError(f"{label} is required or invalid")
        return value

    @classmethod
    def _text(cls, form, key, limit):
        return cls._value(form.get(key), key.replace("_", " "), limit)

    @classmethod
    def _optional(cls, form, key, limit):
        return cls._optional_value(form.get(key), limit)

    @classmethod
    def _optional_value(cls, value, limit):
        return cls._value(value, "optional text", limit) if str(value or "").strip() else None

    @staticmethod
    def _positive_int(form, key, message):
        try:
            value = int(form.get(key, ""))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError) as exc:
            raise MaintenanceError(message) from exc

    @classmethod
    def _optional_positive_int(cls, form, key):
        return cls._positive_int(form, key, f"{key.replace('_', ' ')} is invalid") \
            if str(form.get(key, "")).strip() else None

    @staticmethod
    def _bool(form, key):
        return str(form.get(key, "")).lower() in {"1", "yes", "true", "on"}

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    @staticmethod
    def _unb64(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
