from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from inventory.credentials import credential_status, store_p1s_access_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Privately store or verify Cowboy's local P1S credential."
    )
    parser.add_argument("action", choices=("set", "status"))
    args = parser.parse_args(argv)
    if args.action == "status":
        print(json.dumps(credential_status().safe_summary(), indent=2))
        return 0

    first = getpass.getpass("Enter P1S LAN access code privately: ")
    second = getpass.getpass("Enter it again to confirm: ")
    if first != second:
        print("Credential entries did not match. Nothing was stored.", file=sys.stderr)
        return 2
    status = store_p1s_access_code(first)
    del first, second
    print(json.dumps(status.safe_summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
