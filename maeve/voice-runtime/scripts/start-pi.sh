#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RUNTIME_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SERVER="$RUNTIME_ROOT/broker/server.py"
INDEX="$RUNTIME_ROOT/ui/index.html"
PORT="${1:-48177}"

[ -f "$SERVER" ] || { printf '%s\n' "Required runtime file missing: $SERVER" >&2; exit 1; }
[ -f "$INDEX" ] || { printf '%s\n' "Required runtime file missing: $INDEX" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { printf '%s\n' 'Python 3.11 or 3.12 is required. Nothing was installed.' >&2; exit 1; }

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
case "$PYTHON_VERSION" in 3.11|3.12) ;; *) printf '%s\n' "Python 3.11 or 3.12 required; found $PYTHON_VERSION" >&2; exit 1;; esac

printf '%s\n' "Maeve V2 local URL: http://127.0.0.1:$PORT/"
printf '%s\n' 'Press Ctrl+C in this terminal to stop the runtime.'
exec python3 "$SERVER" --port "$PORT"
