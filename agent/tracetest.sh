#!/usr/bin/env bash
# Exercises agent/trace.py end to end without Letta or the box: a throwaway copy
# of this tree as SINGULARI_HOME (with an empty status/), a bare "origin", the
# orphan trace worktree, then beats: plain, with a prompt edit, rested, poke
# failed, and a loop exit. Asserts the commits and the diff landed. Run from anywhere.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="${SINGULARI_PYTHON:-$HERE/.venv/bin/python3}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export SINGULARI_HOME="$T/home"
mkdir -p "$SINGULARI_HOME/status" "$T/origin"
for d in prompt agent web diary; do cp -R "$HERE/$d" "$SINGULARI_HOME/"; done
rm -rf "$SINGULARI_HOME/web/node_modules" "$SINGULARI_HOME/web/dist" "$SINGULARI_HOME/agent/.last_wake.json"
git init -q --bare "$T/origin"
git -C "$SINGULARI_HOME" init -q && git -C "$SINGULARI_HOME" remote add origin "$T/origin"
git -C "$SINGULARI_HOME" worktree add -q --orphan -b trace .trace

cp "$HERE/agent/fixtures/wake.json" "$SINGULARI_HOME/agent/.last_wake.json"
"$PY" "$HERE/agent/trace.py" 120 120
cp "$HERE/agent/fixtures/wake.json" "$SINGULARI_HOME/agent/.last_wake.json"
printf '\nThe rest is yours, and so is this line.\n' >> "$SINGULARI_HOME/prompt/situation.md"
"$PY" "$HERE/agent/trace.py" 3600 120
"$PY" "$HERE/agent/trace.py" 120 120
"$PY" "$HERE/agent/trace.py" --exit 143

LEDGER="$(cat "$SINGULARI_HOME"/.trace/trace/*.jsonl)"
COMMITS="$(git -C "$T/origin" log --format='%an %s' trace)"
fail() { echo "FAIL: $*" >&2; echo "$LEDGER" | cut -c1-300 >&2; echo "$COMMITS" >&2; exit 1; }
[ "$(echo "$COMMITS" | grep -c '^observatory ')" = 4 ] || fail "expected 4 observatory commits"
echo "$COMMITS" | grep -q 'wake 2' || fail "no wake 2 commit"
echo "$COMMITS" | grep -q 'poke-failed' || fail "no poke-failed commit"
echo "$COMMITS" | grep -q 'loop-exit' || fail "no loop-exit commit"
echo "$LEDGER" | grep -q '"wake": 1' && ! echo "$LEDGER" | grep -q '"wake": 1.*"changed"' || fail "first beat must seed the snapshot, not report changes"
echo "$LEDGER" | grep -q '"wake": 2.*"changed".*prompt/situation.md.*+The rest is yours' || fail "wake 2 missing the situation.md diff"
echo "$LEDGER" | grep -q '"wake": 2.*"rest": true' || fail "wake 2 not marked as rested"
echo "$LEDGER" | grep -q '"event": "loop-exit", "code": 143' || fail "loop-exit 143 not recorded"
"$PY" -c "import json,sys; i=json.load(open('$SINGULARI_HOME/.trace/trace/index.json')); assert i['wakes']==2 and i['rests']==1 and i['exits'][0]['code']==143 and i['files_changed_since_birth']==['prompt/situation.md'], i"
echo "trace OK: 2 wakes, 1 rest, 1 poke-failed, loop-exit 143, situation.md diff recorded"
