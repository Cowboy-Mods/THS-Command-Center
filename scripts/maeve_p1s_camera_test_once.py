from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from inventory.credentials import CredentialStoreError, load_p1s_access_code
from inventory.maeve_local_config import load_printer_host
from inventory.p1s_camera import CameraValidationError, capture_one_frame, write_validated_frame


RUNTIME = Path.home() / "Documents" / "THS-Command-Center-Data" / "runtime" / "camera-validation"
FRAME = RUNTIME / "maeve-p1s-validation-frame.jpg"
RESULT = RUNTIME / "maeve-p1s-camera-result.json"


def write_result(value: dict[str, object]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    temporary = RESULT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULT)


def main() -> int:
    result: dict[str, object] = {
        "attempt_count": 0,
        "tcp_accepted": False,
        "tls_established": False,
        "authentication_accepted": False,
        "frame_received": False,
        "jpeg_valid": False,
        "commands_sent": 0,
        "control_capable": False,
        "captured_at": None,
    }
    try:
        access_code = load_p1s_access_code()
        if not access_code.strip():
            raise CredentialStoreError("protected credential is empty")
    except CredentialStoreError:
        result.update(stage="credential", category="protected_credential_unavailable")
        write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 3

    try:
        result["attempt_count"] = 1
        frame = capture_one_frame(load_printer_host(), access_code, timeout_seconds=20.0)
        result.update(tcp_accepted=True, tls_established=True, authentication_accepted=True)
        write_validated_frame(FRAME, frame)
        result.update(
            frame_received=True,
            jpeg_valid=True,
            width=frame.width,
            height=frame.height,
            tls_version=frame.tls_version,
            tls_cipher=frame.tls_cipher,
            captured_at=datetime.now(timezone.utc).isoformat(),
            stage="complete",
            category="success",
        )
        write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except CameraValidationError as exc:
        result.update(stage=exc.stage, category=exc.category)
        if exc.stage not in {"configuration", "credential", "tcp"}:
            result["tcp_accepted"] = True
        if exc.stage not in {"configuration", "credential", "tcp", "tls"}:
            result["tls_established"] = True
        write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 2
    finally:
        access_code = ""


if __name__ == "__main__":
    raise SystemExit(main())
