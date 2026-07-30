from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .actions import ActionContext
from .db import connect


class ProductionError(ValueError):
    """Production history input is incomplete or violates a safety rule."""


class ProductionService:
    """Controlled write boundary for production, evidence, maintenance, and progress."""

    MODULE = "print-registry"

    def __init__(self, database, context: ActionContext):
        self.database = Path(database)
        self.context = context

    def complete_print(
        self, *, job_name: str, plate_name: str | None, part_name: str,
        inspection_status: str, completed_at: str, quantity: int = 1,
        completion_time_accuracy: str = "exact",
        defect_notes: str | None = None, printer_id: int | None = None,
        project_id: int | None = None, notes: str | None = None,
        request_nonce: str | None = None,
    ) -> dict:
        job_name = self._required(job_name, "job name", 200)
        part_name = self._required(part_name, "part name", 200)
        plate_name = self._optional(plate_name, 200)
        defect_notes = self._optional(defect_notes, 2000)
        notes = self._optional(notes, 2000)
        self._timestamp(completed_at, "completion time")
        if completion_time_accuracy not in {"exact", "estimated", "unknown"}:
            raise ProductionError("invalid completion time accuracy")
        if inspection_status not in {"accepted", "accepted_with_defect", "rejected"}:
            raise ProductionError("select a completed-print inspection result")
        if inspection_status == "accepted_with_defect" and not defect_notes:
            raise ProductionError("accepted-with-defect records require defect notes")
        if quantity <= 0:
            raise ProductionError("quantity must be positive")

        with closing(connect(self.database)) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if request_nonce and db.execute(
                    "SELECT 1 FROM audit_events WHERE request_nonce=?", (request_nonce,)
                ).fetchone():
                    raise ProductionError("this print completion was already recorded")
                self._foreign(db, "printers", printer_id, "printer")
                self._foreign(db, "projects", project_id, "project")
                print_number = self._next_number(db, "print_records", "print_number", "THS-PRT")
                record_id = db.execute(
                    """INSERT INTO print_records(
                    print_number,project_id,printer_id,job_name,plate_name,part_name,quantity,
                    status,inspection_status,defect_notes,completed_at,operator,notes,
                    completion_time_accuracy)
                    VALUES (?,?,?,?,?,?,?,'completed',?,?,?,?,?,?)""",
                    (
                        print_number, project_id, printer_id, job_name, plate_name, part_name,
                        quantity, inspection_status, defect_notes, completed_at,
                        self.context.actor, notes, completion_time_accuracy,
                    ),
                ).lastrowid
                audit_id = self._audit(
                    db, "complete_print", "print_record", record_id, print_number,
                    f"Completed {part_name}: {inspection_status.replace('_', ' ')}",
                    {
                        "job_name": job_name, "plate_name": plate_name,
                        "inspection_status": inspection_status, "defect_notes": defect_notes,
                        "completed_at": completed_at,
                        "completion_time_accuracy": completion_time_accuracy,
                        "quantity": quantity,
                    },
                    request_nonce=request_nonce,
                )
                db.commit()
                return {
                    "id": record_id, "print_number": print_number,
                    "audit_id": audit_id, "inspection_status": inspection_status,
                }
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ProductionError(str(exc)) from exc

    def add_evidence(
        self, print_record_id: int, *, evidence_type: str, file_path: str,
        sha256: str | None = None, caption: str | None = None,
        captured_at: str | None = None,
    ) -> dict:
        if evidence_type not in {"photo", "video"}:
            raise ProductionError("evidence must be a photo or video")
        normalized = self._required(file_path, "evidence file path", 2000)
        path = Path(normalized)
        if not path.is_absolute():
            raise ProductionError("evidence file path must be absolute")
        if sha256 is None:
            if not path.is_file():
                raise ProductionError("evidence file does not exist")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            sha256 = digest.hexdigest()
        sha256 = sha256.lower()
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ProductionError("evidence SHA-256 must contain 64 hexadecimal characters")
        if captured_at:
            self._timestamp(captured_at, "capture time")
        with closing(connect(self.database)) as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute(
                "SELECT print_number FROM print_records WHERE id=?", (print_record_id,)
            ).fetchone()
            if not record:
                raise ProductionError("print record not found")
            evidence_id = db.execute(
                """INSERT INTO print_evidence(
                print_record_id,evidence_type,file_path,sha256,caption,captured_at,added_by)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    print_record_id, evidence_type, str(path), sha256,
                    self._optional(caption, 1000), captured_at, self.context.actor,
                ),
            ).lastrowid
            audit_id = self._audit(
                db, "add_print_evidence", "print_evidence", evidence_id,
                record["print_number"], f"Added {evidence_type} evidence",
                {"file_path": str(path), "sha256": sha256, "print_record_id": print_record_id},
            )
            db.commit()
            return {"id": evidence_id, "audit_id": audit_id, "sha256": sha256}

    def log_maintenance(
        self, *, event_type: str, summary: str, occurred_at: str,
        severity: str = "info", details: str | None = None,
        printer_id: int | None = None, related_print_id: int | None = None,
        resolved_at: str | None = None,
    ) -> dict:
        event_type = self._required(event_type, "event type", 100)
        summary = self._required(summary, "summary", 500)
        details = self._optional(details, 2000)
        if severity not in {"info", "warning", "critical"}:
            raise ProductionError("invalid maintenance severity")
        self._timestamp(occurred_at, "event time")
        if resolved_at:
            self._timestamp(resolved_at, "resolution time")
        with closing(connect(self.database)) as db:
            db.execute("BEGIN IMMEDIATE")
            self._foreign(db, "printers", printer_id, "printer")
            self._foreign(db, "print_records", related_print_id, "print record")
            number = self._next_number(
                db, "maintenance_events", "event_number", "THS-MNT"
            )
            event_id = db.execute(
                """INSERT INTO maintenance_events(
                event_number,printer_id,event_type,summary,details,severity,occurred_at,
                resolved_at,actor,related_print_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    number, printer_id, event_type, summary, details, severity,
                    occurred_at, resolved_at, self.context.actor, related_print_id,
                ),
            ).lastrowid
            audit_id = self._audit(
                db, "log_maintenance_event", "maintenance_event", event_id, number,
                summary, {"event_type": event_type, "severity": severity, "details": details},
            )
            db.commit()
            return {"id": event_id, "event_number": number, "audit_id": audit_id}

    def update_project_progress(
        self, project_id: int, *, mode: str, percent: float | None = None,
        stage: str | None = None, note: str | None = None,
    ) -> int:
        if mode not in {"exact", "estimated", "stage", "unknown"}:
            raise ProductionError("invalid project progress mode")
        if mode in {"exact", "estimated"}:
            if percent is None or not 0 <= percent <= 100:
                raise ProductionError("exact or estimated progress requires 0 to 100 percent")
        elif percent is not None:
            raise ProductionError("stage or unknown progress cannot claim a percentage")
        stage = self._optional(stage, 200)
        note = self._optional(note, 1000)
        if mode == "stage" and not stage:
            raise ProductionError("stage progress requires a stage name")
        with closing(connect(self.database)) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if not previous:
                raise ProductionError("project not found")
            db.execute(
                """UPDATE projects SET progress_mode=?,progress_percent=?,
                progress_stage=?,progress_note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (mode, percent, stage, note, project_id),
            )
            return_id = self._audit(
                db, "update_project_progress", "project", project_id,
                previous["project_code"], f"Project progress recorded as {mode}",
                {"mode": mode, "percent": percent, "stage": stage, "note": note},
            )
            db.commit()
            return return_id

    @staticmethod
    def audit_history(database, limit: int = 200) -> list[dict]:
        limit = min(max(int(limit), 1), 500)
        with closing(connect(database)) as db:
            rows = db.execute(
                """SELECT occurred_at,actor,module,origin,event_type,entity_type,
                entity_human_id,summary,details FROM audit_events
                ORDER BY occurred_at DESC,id DESC LIMIT ?""", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def _audit(
        self, db, event_type: str, entity_type: str, entity_id: int | None,
        human_id: str | None, summary: str, details: dict | None,
        *, request_nonce: str | None = None,
    ) -> int:
        return db.execute(
            """INSERT INTO audit_events(
            event_uuid,actor,module,origin,event_type,entity_type,entity_id,
            entity_human_id,summary,details,request_nonce)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), self.context.actor, self.context.module,
                self.context.origin, event_type, entity_type, entity_id, human_id,
                summary, json.dumps(details, sort_keys=True) if details else None,
                request_nonce,
            ),
        ).lastrowid

    @staticmethod
    def _next_number(db, table: str, column: str, prefix: str) -> str:
        allowed = {
            ("print_records", "print_number"),
            ("maintenance_events", "event_number"),
        }
        if (table, column) not in allowed:
            raise RuntimeError("unsupported permanent number sequence")
        maximum = db.execute(
            f"SELECT MAX(CAST(SUBSTR({column},LENGTH(?)+2) AS INTEGER)) "
            f"FROM {table} WHERE {column} LIKE ?",
            (prefix, f"{prefix}-%"),
        ).fetchone()[0] or 0
        return f"{prefix}-{maximum + 1:06d}"

    @staticmethod
    def _foreign(db, table: str, row_id: int | None, label: str) -> None:
        if row_id is None:
            return
        if table not in {"printers", "projects", "print_records"}:
            raise RuntimeError("unsupported foreign-key check")
        if not db.execute(f"SELECT 1 FROM {table} WHERE id=?", (row_id,)).fetchone():
            raise ProductionError(f"{label} not found")

    @staticmethod
    def _required(value, label: str, limit: int) -> str:
        value = str(value or "").strip()
        if not value or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ProductionError(f"{label} is required or invalid")
        return value

    @classmethod
    def _optional(cls, value, limit: int) -> str | None:
        return cls._required(value, "optional text", limit) if str(value or "").strip() else None

    @staticmethod
    def _timestamp(value: str, label: str) -> None:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ProductionError(f"{label} must be valid RFC3339") from exc
        if parsed.tzinfo is None:
            raise ProductionError(f"{label} must include a UTC offset")
