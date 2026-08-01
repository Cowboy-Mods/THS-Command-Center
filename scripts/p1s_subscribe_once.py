from __future__ import annotations

import json
import sys
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from inventory.p1s_mqtt import SubscribeOnlyConnectionError, capture_one_report
from inventory.telemetry import P1STelemetryConfig, parse_bambu_status


def main() -> int:
    try:
        config = P1STelemetryConfig.from_protected_store()
        payload = capture_one_report(config)
        observed = parse_bambu_status(
            payload, stale_after_seconds=config.stale_after_seconds
        )
    except (SubscribeOnlyConnectionError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = observed.as_dashboard_projection()
    result["observation_timestamp"] = observed.received_at.isoformat().replace(
        "+00:00", "Z"
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
