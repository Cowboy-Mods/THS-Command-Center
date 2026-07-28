from __future__ import annotations

import json
import sqlite3
from typing import Any


class CorrectionPreviewError(ValueError):
    """The requested zero-write correction preview cannot be proven safe."""


def build_spool_correction_preview(
    db: sqlite3.Connection,
    *,
    outgoing_permanent_id: str,
    incoming_permanent_id: str,
    outgoing_storage_location_name: str,
    incoming_destination_equipment: str,
    incoming_destination_slot_number: int,
) -> dict[str, Any]:
    """Inspect authoritative state and project a schema-19 correction without writes."""
    before_changes = db.total_changes
    outgoing = _spool(db, outgoing_permanent_id)
    incoming = _spool(db, incoming_permanent_id)
    if outgoing["id"] == incoming["id"]:
        raise CorrectionPreviewError("outgoing and incoming spools must be different")

    outgoing_assignment = _active_assignment(db, outgoing["id"])
    incoming_assignment = _active_assignment(db, incoming["id"])
    if not outgoing_assignment:
        raise CorrectionPreviewError("outgoing spool is not actively assigned to an AMS slot")
    if not incoming_assignment:
        raise CorrectionPreviewError("incoming spool is not actively assigned to an AMS slot")
    if outgoing["state"] != "loaded" or incoming["state"] != "loaded":
        raise CorrectionPreviewError("both spools must currently be loaded")

    storage = _one(
        db,
        """
        SELECT id,name,kind,parent_id,archived_at
        FROM locations
        WHERE name=? AND kind='storage' AND archived_at IS NULL
        """,
        (outgoing_storage_location_name,),
        "active outgoing storage location",
    )
    destination = _one(
        db,
        """
        SELECT es.id slot_id,es.location_id,e.name equipment_name,es.slot_number
        FROM equipment_slots es
        JOIN equipment e ON e.id=es.equipment_id
        WHERE e.name=? AND es.slot_number=? AND e.archived_at IS NULL
        """,
        (incoming_destination_equipment, incoming_destination_slot_number),
        "incoming destination AMS slot",
    )
    if destination["slot_id"] != outgoing_assignment["slot_id"]:
        raise CorrectionPreviewError(
            "incoming destination must be the slot vacated by the outgoing spool"
        )
    if incoming_assignment["slot_id"] == destination["slot_id"]:
        raise CorrectionPreviewError("incoming spool is already in the destination slot")

    plan = {
        "mode": "zero_write_correction_preview",
        "schema_version": _schema_version(db),
        "current": {
            "outgoing": outgoing,
            "outgoing_assignment": outgoing_assignment,
            "incoming": incoming,
            "incoming_assignment": incoming_assignment,
        },
        "history": {
            "outgoing": _history(db, outgoing["id"]),
            "incoming": _history(db, incoming["id"]),
        },
        "proposed": {
            "outgoing_disposition": "storage",
            "outgoing_destination_location": storage,
            "incoming_disposition": "open",
            "incoming_source_slot": incoming_assignment,
            "incoming_destination_slot": destination,
            "leave_incoming_source_slot_empty": True,
            "preserve_permanent_ids": True,
            "preserve_quantities": True,
        },
        "row_changes": _row_changes(
            outgoing, incoming, outgoing_assignment, incoming_assignment,
            storage, destination,
        ),
        "expected_audit_actions": [
            {
                "order": 1,
                "action_type": "unload_instance_from_ams",
                "permanent_id": outgoing["permanent_id"],
            },
            {
                "order": 2,
                "action_type": "unload_instance_from_ams",
                "permanent_id": incoming["permanent_id"],
            },
            {
                "order": 3,
                "action_type": "load_instance_into_ams",
                "permanent_id": incoming["permanent_id"],
            },
        ],
        "confirmation_questions": [
            "Confirm the physical spool in AMS 2 Slot 1 is THS-FIL-000039.",
            "Confirm THS-FIL-000032 is physically out of AMS 2 Slot 1 and should be stored at Open-Spool Wall.",
            "Confirm THS-FIL-000039 is Overture PLA Black and THS-FIL-000032 is Bambu Lab PLA Basic Black.",
            "Confirm both spools remain open and partially used; no remaining weight will be changed because neither weight is proven.",
            "Confirm AMS 1 Slot 4 should be left empty after the correction.",
        ],
    }
    if db.total_changes != before_changes:
        raise AssertionError("correction preview performed a database write")
    return plan


def _row_changes(
    outgoing, incoming, outgoing_assignment, incoming_assignment, storage, destination
):
    return [
        {
            "table": "inventory_workflow_transactions",
            "operation": "INSERT",
            "fields": {
                "workflow_type": "replace_active_filament_spool",
                "current_instance_id": outgoing["id"],
                "replacement_instance_id": None,
                "destination_slot_id": None,
                "outgoing_disposition": "storage",
                "outgoing_destination_location_id": storage["id"],
                "outgoing_destination_slot_id": None,
                "incoming_disposition": "open",
                "incoming_source_location_id": None,
                "incoming_source_slot_id": incoming_assignment["slot_id"],
                "incoming_instance_id": incoming["id"],
                "incoming_destination_slot_id": destination["slot_id"],
            },
            "generated_at_apply_time": [
                "id", "workflow_uuid", "review_nonce", "occurred_at",
                "actor", "module", "origin", "reason",
            ],
        },
        {
            "table": "inventory_instances",
            "operation": "UPDATE",
            "row_id": outgoing["id"],
            "fields": {
                "state": {"before": "loaded", "after": "open"},
                "location_id": {
                    "before": outgoing["location_id"], "after": storage["id"]
                },
                "updated_at": {"before": outgoing["updated_at"], "after": "apply time"},
            },
        },
        {
            "table": "ams_assignments",
            "operation": "UPDATE",
            "row_id": outgoing_assignment["assignment_id"],
            "fields": {
                "unloaded_at": {"before": None, "after": "apply time"},
                "unload_transaction_id": {
                    "before": None, "after": "generated unload transaction id"
                },
            },
        },
        {
            "table": "inventory_instances",
            "operation": "UPDATE",
            "row_id": incoming["id"],
            "fields": {
                "state": {"before": "loaded", "after": "open"},
                "location_id": {
                    "before": incoming["location_id"],
                    "after": destination["location_id"],
                },
                "updated_at": {"before": incoming["updated_at"], "after": "apply time"},
            },
            "note": "Intermediate unload state; final load below restores state=loaded.",
        },
        {
            "table": "ams_assignments",
            "operation": "UPDATE",
            "row_id": incoming_assignment["assignment_id"],
            "fields": {
                "unloaded_at": {"before": None, "after": "apply time"},
                "unload_transaction_id": {
                    "before": None, "after": "generated unload transaction id"
                },
            },
        },
        {
            "table": "inventory_instances",
            "operation": "UPDATE",
            "row_id": incoming["id"],
            "fields": {
                "state": {"before": "open", "after": "loaded"},
                "location_id": {
                    "before": destination["location_id"],
                    "after": destination["location_id"],
                },
                "updated_at": {"before": "apply time", "after": "apply time"},
            },
            "note": "Final authoritative state after the atomic workflow.",
        },
        {
            "table": "ams_assignments",
            "operation": "INSERT",
            "fields": {
                "slot_id": destination["slot_id"],
                "instance_id": incoming["id"],
                "loaded_at": "apply time",
                "unloaded_at": None,
                "load_transaction_id": "generated load transaction id",
                "unload_transaction_id": None,
            },
        },
        {
            "table": "inventory_transactions",
            "operation": "INSERT",
            "row_count": 3,
            "transaction_types": ["unload", "unload", "load"],
        },
        {
            "table": "transaction_lines",
            "operation": "INSERT",
            "row_count": 3,
            "note": "One immutable line for each unload/load transaction.",
        },
        {
            "table": "inventory_actions",
            "operation": "INSERT",
            "row_count": 3,
            "action_types": [
                "unload_instance_from_ams",
                "unload_instance_from_ams",
                "load_instance_into_ams",
            ],
            "note": "Each action stores immutable before/after JSON and the parent workflow id.",
        },
    ]


def _spool(db, permanent_id):
    return _one(
        db,
        """
        SELECT ii.id,ii.permanent_id,ii.catalog_item_id,ii.state,ii.condition,
               ii.location_id,ii.original_quantity,ii.remaining_quantity,
               ii.unit_id,ii.opened_at,ii.emptied_at,ii.archived_at,ii.notes,
               ii.verified,ii.created_at,ii.updated_at,
               m.name manufacturer,ci.name catalog_name,ci.product_line,ci.variant
        FROM inventory_instances ii
        JOIN catalog_items ci ON ci.id=ii.catalog_item_id
        LEFT JOIN manufacturers m ON m.id=ci.manufacturer_id
        WHERE ii.permanent_id=?
        """,
        (permanent_id,),
        f"spool {permanent_id}",
    )


def _active_assignment(db, instance_id):
    row = db.execute(
        """
        SELECT aa.id assignment_id,aa.slot_id,aa.loaded_at,
               aa.load_transaction_id,e.name equipment_name,es.slot_number,
               es.location_id
        FROM ams_assignments aa
        JOIN equipment_slots es ON es.id=aa.slot_id
        JOIN equipment e ON e.id=es.equipment_id
        WHERE aa.instance_id=? AND aa.unloaded_at IS NULL
        """,
        (instance_id,),
    ).fetchone()
    return dict(row) if row else None


def _history(db, instance_id):
    actions = [
        dict(row) for row in db.execute(
            """
            SELECT id,action_uuid,occurred_at,actor,module,origin,action_type,reason,
                   previous_state,new_state,transaction_id,workflow_transaction_id,
                   request_nonce
            FROM inventory_actions
            WHERE affected_entity_type='inventory_instance'
              AND affected_entity_id=?
            ORDER BY id
            """,
            (instance_id,),
        )
    ]
    for action in actions:
        for field in ("previous_state", "new_state"):
            if action[field]:
                action[field] = json.loads(action[field])
    assignments = [
        dict(row) for row in db.execute(
            """
            SELECT aa.id assignment_id,aa.slot_id,aa.loaded_at,aa.unloaded_at,
                   aa.load_transaction_id,aa.unload_transaction_id,
                   e.name equipment_name,es.slot_number
            FROM ams_assignments aa
            JOIN equipment_slots es ON es.id=aa.slot_id
            JOIN equipment e ON e.id=es.equipment_id
            WHERE aa.instance_id=? ORDER BY aa.id
            """,
            (instance_id,),
        )
    ]
    workflow_columns = {
        row["name"] for row in db.execute(
            "PRAGMA table_info(inventory_workflow_transactions)"
        )
    }
    incoming_clause = (
        " OR incoming_instance_id=?" if "incoming_instance_id" in workflow_columns else ""
    )
    workflow_params = (
        (instance_id, instance_id, instance_id)
        if incoming_clause else (instance_id, instance_id)
    )
    workflows = [
        dict(row) for row in db.execute(
            "SELECT * FROM inventory_workflow_transactions "
            "WHERE current_instance_id=? OR replacement_instance_id=?"
            f"{incoming_clause} ORDER BY id",
            workflow_params,
        )
    ]
    return {"actions": actions, "assignments": assignments, "workflows": workflows}


def _schema_version(db):
    row = db.execute(
        "SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 1"
    ).fetchone()
    return int(row[0].split("_", 1)[0]) if row else 0


def _one(db, sql, params, label):
    rows = [dict(row) for row in db.execute(sql, params)]
    if len(rows) != 1:
        raise CorrectionPreviewError(f"expected exactly one {label}")
    return rows[0]
