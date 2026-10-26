#!/usr/bin/env bash
# Exercises agent/heartbeat.sh without a model: a stub interpreter stands in
# for python and logs every call. Checks that the loop beats, that an edit to
# the script takes effect on the next beat, that a TERM mid-sleep ends it with
# 143, and that the exit is recorded exactly once.
set -eu
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/agent"
cp "$(dirname "$0")/heartbeat.sh" "$T/agent/heartbeat.sh"
sed -i.bak 's/^INTERVAL=[0-9]*$/INTERVAL=1/' "$T/agent/heartbeat.sh" && rm "$T/agent/heartbeat.sh.bak"

cat > "$T/stub" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
case "$1" in agent/rest.py) echo "$2" ;; esac
EOF
chmod +x "$T/stub"
export STUB_LOG="$T/calls" SINGULARI_PYTHON="$T/stub"

bash "$T/agent/heartbeat.sh" &
loop=$!
sleep 2.5
sed -i.bak 's/^INTERVAL=1$/INTERVAL=7/' "$T/agent/heartbeat.sh" && rm "$T/agent/heartbeat.sh.bak"
sleep 2.5
kill -TERM "$loop"
wait "$loop" && code=0 || code=$?

fail() { echo "FAIL: $*" >&2; cat "$STUB_LOG" >&2; exit 1; }
[ "$code" = 143 ] || fail "expected exit 143, got $code"
[ "$(grep -c '^agent/brain.py$' "$STUB_LOG")" -ge 3 ] || fail "expected at least 3 beats"
grep -q '^agent/trace.py 1 1$' "$STUB_LOG" || fail "first beats did not use the interval 1"
grep -q '^agent/trace.py 7 7$' "$STUB_LOG" || fail "the edited interval 7 never took effect"
[ "$(grep -c '^agent/trace.py --exit 143$' "$STUB_LOG")" = 1 ] || fail "exit recorded $(grep -c -- '--exit' "$STUB_LOG") times, expected once"
echo "heartbeat OK: beats, re-read the edit, exit 143 recorded once"
