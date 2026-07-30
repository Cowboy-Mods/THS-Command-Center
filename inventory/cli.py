from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ams_onboarding import AMSOnboardingError, AMSOnboardingService
from .db import DEFAULT_DB, connect, migrate
from .importer import import_csv
from .web import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="ths-inventory")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    imp = sub.add_parser("import")
    imp.add_argument("csv", type=Path)
    imp.add_argument("--apply", action="store_true", help="Commit valid rows (default is dry-run)")
    imp.add_argument("--allow-unverified", action="store_true")
    web = sub.add_parser("serve", help="Start the read-only local inventory dashboard")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8787)
    onboarding = sub.add_parser(
        "ams-onboard",
        help="Dry-run or explicitly commit the controlled AMS onboarding plan",
    )
    onboarding.add_argument(
        "--commit",
        action="store_true",
        help="Apply the exact 29-insert/2-update plan (default is zero-write dry-run)",
    )
    onboarding.add_argument(
        "--confirm",
        help="Required exact confirmation phrase when --commit is supplied",
    )
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.database, args.host, args.port)
        return
    if args.command == "ams-onboard":
        service = AMSOnboardingService(args.database)
        try:
            if args.commit:
                result = service.commit(confirmation=args.confirm or "")
            else:
                if args.confirm:
                    parser.error("--confirm is valid only with --commit")
                result = service.preview()
        except AMSOnboardingError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return
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

