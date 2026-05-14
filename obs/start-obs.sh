#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/obs.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Obs server already running (PID $(cat "$PID_FILE"))"
  echo "Dashboard: http://localhost:${OBS_PORT:-4000}"
  exit 0
fi

if ! command -v bun &>/dev/null; then
  echo "Error: bun not found. Install: curl -fsSL https://bun.sh/install | bash" >&2
  exit 1
fi

bun run "$SCRIPT_DIR/server/index.ts" &
echo $! > "$PID_FILE"
echo "Obs server started — http://localhost:${OBS_PORT:-4000} (PID $!)"
