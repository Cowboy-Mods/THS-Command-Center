from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
DEFAULT_DB = ROOT / "var" / "inventory.sqlite3"


def connect(path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def migrate(db: sqlite3.Connection) -> list[str]:
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = {r[0] for r in db.execute("SELECT name FROM schema_migrations")}
    names: list[str] = []
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if migration.name in applied:
            continue
        db.executescript(migration.read_text(encoding="utf-8"))
        db.execute("INSERT INTO schema_migrations(name) VALUES (?)", (migration.name,))
        db.commit()
        names.append(migration.name)
    return names


def active_filament_summary(db: sqlite3.Connection):
    return db.execute(
        """
        SELECT m.name manufacturer, p.product_line, p.variant,
               COUNT(i.id) active_rolls,
               SUM(i.state='sealed') sealed_rolls,
               SUM(i.state='open') open_rolls,
               SUM(i.state='loaded') loaded_rolls,
               SUM(i.remaining_quantity) available_grams,
               COALESCE((SELECT SUM(r.quantity)
                 FROM reservations r WHERE r.catalog_item_id=p.id
                   AND r.status='active'), 0) reserved_grams
        FROM catalog_items p
        JOIN manufacturers m ON m.id=p.manufacturer_id
        JOIN inventory_instances i ON i.catalog_item_id=p.id
        WHERE p.item_type_id=(SELECT id FROM item_types WHERE name='Filament')
          AND i.archived_at IS NULL AND i.state NOT IN ('empty','archived')
        GROUP BY p.id ORDER BY m.name, p.product_line, p.variant
        """
    ).fetchall()


def project_material_status(db: sqlite3.Connection, project_id: int):
    """Compare a small BOM against active individual and quantity stock."""
    return db.execute(
        """
        WITH individual AS (
          SELECT catalog_item_id,unit_id,SUM(remaining_quantity) quantity
          FROM inventory_instances
          WHERE archived_at IS NULL AND state NOT IN ('empty','archived')
          GROUP BY catalog_item_id,unit_id
        ), bulk AS (
          SELECT catalog_item_id,unit_id,SUM(quantity) quantity FROM stock_lots
          WHERE archived_at IS NULL GROUP BY catalog_item_id,unit_id
        ), available AS (
          SELECT catalog_item_id,unit_id,SUM(quantity) quantity FROM (
            SELECT * FROM individual UNION ALL SELECT * FROM bulk
          ) GROUP BY catalog_item_id,unit_id
        ), reserved AS (
          SELECT catalog_item_id,unit_id,SUM(quantity) quantity FROM reservations
          WHERE status='active' GROUP BY catalog_item_id,unit_id
        )
        SELECT pr.id requirement_id,pr.quantity required_quantity,
          COALESCE(a.quantity,0)-COALESCE(r.quantity,0) available_quantity,
          MAX(0,pr.quantity-(COALESCE(a.quantity,0)-COALESCE(r.quantity,0))) shortage_quantity,
          CASE WHEN COALESCE(a.quantity,0)-COALESCE(r.quantity,0)>=pr.quantity
               THEN 'available' ELSE 'shortage' END status
        FROM project_requirements pr
        LEFT JOIN available a ON a.catalog_item_id=COALESCE(pr.catalog_item_id,pr.preferred_catalog_item_id)
          AND a.unit_id=pr.unit_id
        LEFT JOIN reserved r ON r.catalog_item_id=a.catalog_item_id AND r.unit_id=a.unit_id
        WHERE pr.project_id=?
        """,
        (project_id,),
    ).fetchall()


