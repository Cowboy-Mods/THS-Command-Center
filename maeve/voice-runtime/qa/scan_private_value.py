"""Read an authorized comparison value from stdin; print only match paths.

Never put a real comparison value in arguments, environment settings or files.
The caller owns authorization for obtaining the value; this tool reads no
credentials or private installation. Empty comparison input fails closed.
"""
import json
import sys
from pathlib import Path
from test_public_release import private_matches

if __name__ == '__main__':
    value = sys.stdin.buffer.read(4096).strip()
    if not value or len(value) >= 4096:
        raise SystemExit('COMPARISON_INPUT_REJECTED')
    matches = private_matches(Path(__file__).resolve().parent.parent, value)
    value = None
    print(json.dumps({'privateValueMatches': matches, 'count': len(matches)}))
    raise SystemExit(1 if matches else 0)
