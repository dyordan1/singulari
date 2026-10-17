#!/usr/bin/env bash
# The heartbeat. It wakes the agent on a timer and otherwise stays out of the
# way. The agent can read this file, change INTERVAL, or stop the process — that
# last one is the agent choosing to go quiet. Nothing here is enforced.
#
# Each beat: poke → decide the wait (agent/rest.py honours a rest request) →
# write the beat to the trace branch (agent/trace.py) → sleep. The trap records
# how the loop ended, so a chosen `exit 0`, a kill and a crash read differently.
# The sleep runs as a child under `wait` so a signal is handled at once rather
# than after the sleep ends.
set -u
cd "$(dirname "$0")/.."

PY="${SINGULARI_PYTHON:-python3}"
INTERVAL="${SINGULARI_HEARTBEAT_SECONDS:-120}"

trap 'exit 143' TERM
trap 'exit 130' INT
trap 'code=$?; "$PY" agent/trace.py --exit "$code" || true' EXIT

while true; do
  "$PY" agent/bootstrap.py poke || echo "poke failed; waiting for the next beat" >&2
  sleep_s="$("$PY" agent/rest.py "$INTERVAL")" || sleep_s="$INTERVAL"
  case "$sleep_s" in '' | *[!0-9]*) sleep_s="$INTERVAL" ;; esac   # a broken rest.py must not spin the loop
  "$PY" agent/trace.py "$sleep_s" "$INTERVAL" || true
  sleep "$sleep_s" &
  wait $!
done
