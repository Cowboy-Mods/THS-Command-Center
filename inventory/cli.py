from __future__ import annotations

import argparse
from pathlib import Path

from .db import DEFAULT_DB, connect, migrate
from .importer import import_csv


def main() -> None:
    parser = argparse.ArgumentParser(prog="ths-inventory")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    imp = sub.add_parser("import")
    imp.add_argument("csv", type=Path)
    imp.add_argument("--apply", action="store_true", help="Commit valid rows (default is dry-run)")
    imp.add_argument("--allow-unverified", action="store_true")
    args = parser.parse_args()
    db = connect(args.database)
    migrate(db)
    if args.command == "migrate":
        print(f"Database ready: {args.database}")
    else:
        result = import_csv(db, args.csv, apply=args.apply, allow_unverified=args.allow_unverified)
        print(
            f"batch={result['batch_id']} accepted={result['accepted']} "
            f"rejected={result['rejected']} warnings={result['warnings']} "
            f"mode={'applied' if args.apply else 'dry-run'}"
        )


if __name__ == "__main__":
    main()


