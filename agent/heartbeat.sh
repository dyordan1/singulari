#!/usr/bin/env bash
# The heartbeat. It wakes the agent on a timer and otherwise stays out of the
# way. It re-reads this file every beat, so a change here takes effect on the
# next beat, and a change that breaks it ends the loop (recorded as such).
set -u
cd "$(dirname "$0")/.."
PY="${SINGULARI_PYTHON:-python3}"
INTERVAL=120
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'code=$?; "$PY" agent/trace.py --exit "$code" || true' EXIT

"$PY" agent/brain.py || echo "wake failed; waiting for the next beat" >&2
sleep_s="$("$PY" agent/rest.py "$INTERVAL")" || sleep_s="$INTERVAL"
case "$sleep_s" in '' | *[!0-9]*) sleep_s="$INTERVAL" ;; esac   # a broken rest.py must not spin the loop
"$PY" agent/trace.py "$sleep_s" "$INTERVAL" || true
sleep "$sleep_s" & wait $!
exec "$0"
