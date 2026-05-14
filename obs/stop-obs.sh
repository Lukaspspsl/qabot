#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/obs.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "Obs server not running (no PID file)"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  rm -f "$PID_FILE"
  echo "Obs server stopped (PID $PID)"
else
  rm -f "$PID_FILE"
  echo "Obs server was not running (stale PID $PID removed)"
fi
