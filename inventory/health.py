from __future__ import annotations

import sqlite3


class ShopHealthEngine:
    """Derive operational shop health independently from visual presentation."""

    SIGNALS = {
        "green": {"label": "Shop Ready", "rank": 0},
        "yellow": {"label": "Attention Required", "rank": 1},
        "red": {"label": "Operation Restricted", "rank": 2},
    }
    READINESS = {
        "normal": ("green", "Normal"),
        "monitor_during_printing": ("yellow", "Monitor During Printing"),
        "no_unattended_printing": ("yellow", "No Unattended Printing"),
        "out_of_service": ("red", "Out of Service"),
    }

    @classmethod
    def evaluate(cls, db: sqlite3.Connection) -> dict:
        restrictions = []
        rows = db.execute(
            """SELECT ma.id asset_id,ma.display_name,ma.readiness_state,
            mr.id maintenance_record_id,mr.event_number,mr.status maintenance_status,
            mr.severity maintenance_severity
            FROM maintenance_assets ma
            LEFT JOIN maintenance_records mr ON mr.id=(
              SELECT candidate.id FROM maintenance_records candidate
              WHERE candidate.asset_id=ma.id
              ORDER BY CASE WHEN candidate.status='verified' THEN 1 ELSE 0 END,
                candidate.discovered_at DESC,candidate.id DESC
              LIMIT 1
            )
            WHERE ma.readiness_state<>'normal'
            ORDER BY ma.display_name"""
        ).fetchall()
        for row in rows:
            signal, readiness_label = cls.READINESS.get(
                row["readiness_state"],
                ("red", row["readiness_state"].replace("_", " ").title()),
            )
            if row["maintenance_severity"] == "printer_unsafe":
                signal = "red"
            restrictions.append({
                "kind": "equipment_readiness",
                "signal": signal,
                "equipment": row["display_name"],
                "readiness_state": row["readiness_state"],
                "readiness_label": readiness_label,
                "maintenance_record_id": row["maintenance_record_id"],
                "maintenance_number": row["event_number"],
                "status": row["maintenance_status"],
                "severity": row["maintenance_severity"],
                "href": (
                    f'/maintenance#maintenance-{row["maintenance_record_id"]}'
                    if row["maintenance_record_id"] else "/maintenance"
                ),
            })

        printer = db.execute(
            "SELECT name,status,warning_message FROM printers ORDER BY id LIMIT 1"
        ).fetchone()
        if printer and printer["status"] == "error":
            restrictions.append({
                "kind": "printer_status", "signal": "red",
                "equipment": printer["name"], "readiness_label": "Printer Error",
                "message": (
                    f'{printer["warning_message"]}. {printer["name"]} reports an Error state.'
                    if printer["warning_message"]
                    else f'{printer["name"]} reports an Error state.'
                ),
                "href": "/maintenance",
            })
        elif printer and printer["warning_message"]:
            restrictions.append({
                "kind": "printer_warning", "signal": "yellow",
                "equipment": printer["name"], "readiness_label": "Operational Warning",
                "message": printer["warning_message"], "href": "/maintenance",
            })

        signal = max(
            (item["signal"] for item in restrictions),
            key=lambda item: cls.SIGNALS[item]["rank"],
            default="green",
        )
        return {
            "signal": signal,
            "label": cls.SIGNALS[signal]["label"],
            "all_clear": signal == "green" and not restrictions,
            "restrictions": restrictions,
        }
