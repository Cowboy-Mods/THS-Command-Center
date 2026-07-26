from __future__ import annotations

import sys
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import inventory

loaded_application = Path(inventory.__file__).resolve()
expected_application = (project_root / "inventory" / "__init__.py").resolve()
if loaded_application != expected_application:
    raise SystemExit(
        "THS launcher safety check failed: "
        f"expected {expected_application}, loaded {loaded_application}"
    )

print(f"THS application path: {loaded_application}", flush=True)

from inventory.cli import main

main()
