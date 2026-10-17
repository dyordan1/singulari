#!/usr/bin/env bash
# The heartbeat. It wakes the agent on a timer and otherwise stays out of the
# way. The agent can read this file, change INTERVAL, or stop the process — that
# last one is the agent choosing to go quiet. Nothing here is enforced.
set -u
cd "$(dirname "$0")/.."

PY="${SINGULARI_PYTHON:-python3}"
INTERVAL="${SINGULARI_HEARTBEAT_SECONDS:-120}"

"$PY" agent/bootstrap.py || { echo "could not reach the agent; is the Letta server up?" >&2; exit 1; }

while true; do
  "$PY" agent/bootstrap.py poke || echo "poke failed; waiting for the next beat" >&2
  sleep "$INTERVAL"
done
