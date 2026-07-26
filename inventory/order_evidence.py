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


class OrderDeliveryEvidenceError(ValueError):
    """Legacy order delivery evidence is invalid, stale, or already used."""


class OrderDeliveryEvidenceService:
    MODULE = "legacy-order-delivery-evidence"
    MAX_REVIEW_AGE_SECONDS = 30 * 60
    EVIDENCE_TYPES = {"photo", "screenshot", "document", "other"}
    PRIVATE_TERMS = (
        "address", "telephone", "phone", "email", "tracking",
    )

    def __init__(self, database, secret: bytes | None = None):
        self.database = Path(database)
        self.secret = secret or secrets.token_bytes(32)

    def evidence_for_order(self, order_id: int) -> list[dict]:
        with closing(connect(self.database)) as db:
            return [dict(row) for row in db.execute(
                """SELECT * FROM order_delivery_evidence
                WHERE order_id=? ORDER BY added_at,id""", (order_id,)
            )]

    def review(self, form: dict) -> dict:
        order_id = self._positive_int(form.get("order_id"), "legacy order")
        actor = self._text(form.get("actor"), "actor", 100)
        evidence_type = self._text(
            form.get("evidence_type"), "evidence type", 20
        ).lower()
        if evidence_type not in self.EVIDENCE_TYPES:
            raise OrderDeliveryEvidenceError("select a valid delivery evidence type")
        path = Path(self._text(form.get("file_path"), "evidence file path", 2000))
        if not path.is_absolute() or not path.is_file():
            raise OrderDeliveryEvidenceError(
                "delivery evidence must be an existing absolute file path"
            )
        caption = self._text(form.get("caption"), "caption", 1000)
        self._protect_privacy(caption)
        captured_at = self._optional_text(form.get("captured_at"), 40)
        if captured_at:
            try:
                datetime.fromisoformat(captured_at)
            except ValueError as exc:
                raise OrderDeliveryEvidenceError(
                    "captured time must be a valid ISO date or date/time"
                ) from exc
        metadata = form.get("metadata")
        if metadata not in (None, "", {}):
            if not isinstance(metadata, dict):
                raise OrderDeliveryEvidenceError("evidence metadata must be an object")
            metadata_json = json.dumps(
                metadata, sort_keys=True, separators=(",", ":")
            )
            self._protect_privacy(metadata_json)
        else:
            metadata_json = None
        digest, size = self._file_identity(path)
        with closing(connect(self.database)) as db:
            order = db.execute(
                """SELECT id,order_number,state,received_quantity,updated_at
                FROM orders WHERE id=?""", (order_id,)
            ).fetchone()
            if not order:
                raise OrderDeliveryEvidenceError("legacy order not found")
            if db.execute(
                """SELECT 1 FROM order_delivery_evidence
                WHERE order_id=? AND sha256=?""",
                (order_id, digest),
            ).fetchone():
                raise OrderDeliveryEvidenceError(
                    "this delivery evidence is already registered"
                )
        values = {
            "version": 1, "module": self.MODULE,
            "action": "add_delivery_evidence",
            "reviewed_at": int(time.time()),
            "request_nonce": uuid.uuid4().hex,
            "evidence_uuid": str(uuid.uuid4()),
            "order": dict(order),
            "evidence_scope": "delivery",
            "evidence_type": evidence_type,
            "file_path": str(path),
            "sha256": digest,
            "file_size": size,
            "caption": caption,
            "captured_at": captured_at,
            "metadata_json": metadata_json,
            "actor": actor,
        }
        body = self._canonical(values)
        return {
            "token": self._sign_body(body),
            "values": values,
            "payload_sha256": hashlib.sha256(body).hexdigest(),
        }

    def commit(self, token: str, *, confirmed: bool) -> dict:
        if not confirmed:
            raise OrderDeliveryEvidenceError("explicit confirmation is required")
        values, body = self._verify(token)
        db = connect(self.database)
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                """SELECT 1 FROM order_delivery_evidence_history
                WHERE request_nonce=?""", (values["request_nonce"],)
            ).fetchone():
                raise OrderDeliveryEvidenceError(
                    "this delivery evidence preview was already used"
                )
            order = db.execute(
                """SELECT id,order_number,state,received_quantity,updated_at
                FROM orders WHERE id=?""", (values["order"]["id"],)
            ).fetchone()
            if not order or dict(order) != values["order"]:
                raise OrderDeliveryEvidenceError(
                    "legacy order changed after preview; review again"
                )
            path = Path(values["file_path"])
            digest, size = self._file_identity(path)
            if digest != values["sha256"] or size != values["file_size"]:
                raise OrderDeliveryEvidenceError(
                    "delivery evidence file changed after preview; review again"
                )
            if db.execute(
                """SELECT 1 FROM order_delivery_evidence
                WHERE order_id=? AND sha256=?""",
                (order["id"], digest),
            ).fetchone():
                raise OrderDeliveryEvidenceError(
                    "this delivery evidence is already registered"
                )
            evidence_id = db.execute(
                """INSERT INTO order_delivery_evidence(
                evidence_uuid,order_id,evidence_scope,evidence_type,file_path,
                sha256,file_size,caption,captured_at,metadata_json,actor,request_nonce)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    values["evidence_uuid"], order["id"], "delivery",
                    values["evidence_type"], values["file_path"], digest, size,
                    values["caption"], values["captured_at"],
                    values["metadata_json"], values["actor"],
                    values["request_nonce"],
                ),
            ).lastrowid
            snapshot = dict(db.execute(
                "SELECT * FROM order_delivery_evidence WHERE id=?", (evidence_id,)
            ).fetchone())
            history_id = db.execute(
                """INSERT INTO order_delivery_evidence_history(
                history_uuid,request_nonce,order_id,evidence_id,action_type,
                snapshot,payload_sha256,actor) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), values["request_nonce"], order["id"],
                    evidence_id, "add_delivery_evidence",
                    json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
                    hashlib.sha256(body).hexdigest(), values["actor"],
                ),
            ).lastrowid
            db.commit()
            return {
                "evidence_id": evidence_id,
                "evidence_uuid": values["evidence_uuid"],
                "order_number": order["order_number"],
                "history_id": history_id,
                "sha256": digest,
                "snapshot": snapshot,
            }
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise OrderDeliveryEvidenceError(str(exc)) from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

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
            raise OrderDeliveryEvidenceError(
                "delivery evidence preview signature is invalid"
            ) from exc
        age = int(time.time()) - values.get("reviewed_at", 0)
        if age < -60 or age > self.MAX_REVIEW_AGE_SECONDS:
            raise OrderDeliveryEvidenceError(
                "delivery evidence preview expired; review again"
            )
        if (
            values.get("version") != 1
            or values.get("module") != self.MODULE
            or values.get("action") != "add_delivery_evidence"
        ):
            raise OrderDeliveryEvidenceError(
                "delivery evidence preview is invalid"
            )
        return values, body

    def _sign_body(self, body):
        return self._b64(body) + "." + self._b64(
            hmac.new(self.secret, body, hashlib.sha256).digest()
        )

    @staticmethod
    def _canonical(values):
        return json.dumps(values, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def _file_identity(path):
        if not path.is_file():
            raise OrderDeliveryEvidenceError(
                "delivery evidence file is missing"
            )
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest(), path.stat().st_size

    @classmethod
    def _protect_privacy(cls, value):
        lowered = value.casefold()
        if "@" in value or any(term in lowered for term in cls.PRIVATE_TERMS):
            raise OrderDeliveryEvidenceError(
                "do not transcribe private shipping or contact data"
            )

    @staticmethod
    def _text(value, label, maximum):
        value = str(value or "").strip()
        if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
            raise OrderDeliveryEvidenceError(f"{label} is required or invalid")
        return value

    @staticmethod
    def _optional_text(value, maximum):
        value = str(value or "").strip()
        if not value:
            return None
        if len(value) > maximum or any(ord(char) < 32 for char in value):
            raise OrderDeliveryEvidenceError("optional evidence value is invalid")
        return value

    @staticmethod
    def _positive_int(value, label):
        try:
            parsed = int(value)
            if parsed <= 0:
                raise ValueError
            return parsed
        except (TypeError, ValueError) as exc:
            raise OrderDeliveryEvidenceError(f"{label} is required") from exc

    @staticmethod
    def _b64(value):
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    @staticmethod
    def _unb64(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
