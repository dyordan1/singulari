#!/usr/bin/env python3
"""The record. Appends one line per beat to the `trace` branch and pushes it.

Usage: trace.py <sleep_s> <interval_s>   after a beat
       trace.py --exit <code>            from the loop's EXIT trap

The branch is a separate worktree at SINGULARI_HOME/.trace (deploy/SETUP.md
creates it). Each day's beats go in trace/<YYYY-MM-DD>.jsonl; trace/index.json
carries the running totals the website's /status page reads first. A beat's
line holds what the agent did (from agent/.last_wake.json, written by poke),
what changed on disk under prompt/, agent/ and web/ since the previous beat,
each change marked as the agent's own or as a commit that arrived from outside (a
unified diff per text file, from a snapshot kept under status/), and how long the
loop then slept. After the beat, summarize.py writes a line for the wake under
trace/summaries/ and, on the first beat of a new day, the day's brief under
trace/briefs/; and when the agent's replay fills the window, compact.py
summarizes all of it, recorded under trace/compactions/.

Nothing here may stall the heartbeat: every failure prints and exits 0.
"""

import calendar
import difflib
import hashlib
import json
import os
import subprocess
import sys
import time

import compact
import summarize
from status import STATUS_DIR, write_now

HOME = os.environ.get("SINGULARI_HOME", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRACE_WORKTREE = os.path.join(HOME, ".trace")
TRACE_DIR = os.path.join(TRACE_WORKTREE, "trace")
INDEX = os.path.join(TRACE_DIR, "index.json")
LAST_WAKE = os.path.join(HOME, "agent", ".last_wake.json")
SNAPSHOT = os.path.join(STATUS_DIR, "snapshot")
WATCHED = ("prompt", "agent", "web")
SKIP_DIRS = {"node_modules", "dist", ".venv", "__pycache__", "fixtures"}
MAX_DIFF_BYTES = 200_000
AUTHOR = ["-c", "user.name=observatory", "-c", "user.email=observatory@singulari.io"]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stamp(iso: str) -> float:
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


def watched_files():
    for top in WATCHED:
        for root, dirs, files in os.walk(os.path.join(HOME, top)):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(files):
                if name.startswith("."):
                    continue
                yield os.path.relpath(os.path.join(root, name), HOME)


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_text(path):
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_DIFF_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_DIFF_BYTES:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def changes():
    """Diff the watched tree against the snapshot, then refresh the snapshot."""
    first = not os.path.isdir(SNAPSHOT)
    seen, changed = set(), []
    for rel in watched_files():
        seen.add(rel)
        live, kept = os.path.join(HOME, rel), os.path.join(SNAPSHOT, rel)
        digest = sha256_of(live)
        if not first:
            old = read_text(kept) if os.path.exists(kept) else ""
            new = read_text(live)
            if not os.path.exists(kept) or sha256_of(kept) != digest:
                entry = {"path": rel, "sha256": digest}
                if old is not None and new is not None:
                    entry["diff"] = "".join(
                        difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{rel}", f"b/{rel}")
                    )
                changed.append(entry)
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        with open(live, "rb") as src, open(kept, "wb") as dst:
            dst.write(src.read())
    if not first:
        for root, _, files in os.walk(SNAPSHOT):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), SNAPSHOT)
                if rel not in seen:
                    changed.append({"path": rel, "deleted": True})
                    os.remove(os.path.join(root, name))
    return changed


def git_home(*args):
    return subprocess.run(["git", "-C", HOME, *args], capture_output=True, text=True, timeout=60)


def attribute(changed, prev_head, head):
    """Who changed each file: the agent, or a commit that arrived from outside.
    A change is from outside when HEAD moved past commits touching the path by
    someone other than the agent's own git author and the file now matches
    HEAD. A file the agent had edited locally stays its own even if a pull
    touched it too."""
    own = git_home("config", "user.email").stdout.strip()
    for c in changed:
        c["by"] = "agent"
        if not prev_head or head == prev_head:
            continue
        authors = git_home("log", "--format=%ae", f"{prev_head}..{head}", "--", c["path"]).stdout.split()
        matches_head = c.get("deleted") or git_home("diff", "--quiet", head, "--", c["path"]).returncode == 0
        if authors and matches_head and authors[0] != own:
            c["by"], c["author"] = "outside", authors[0]
    return changed


def files_changed_by_agent():
    """Rebuilt from the day files for an index written before changes carried
    `by`: back then a path counts as the agent's if a write, edit or shell call
    of that wake named it."""
    paths = []
    for name in sorted(os.listdir(TRACE_DIR)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(TRACE_DIR, name), encoding="utf-8") as f:
            for line in f:
                beat = json.loads(line)
                named = " ".join(
                    str((m.get("args") or {}).get("path") or (m.get("args") or {}).get("command") or "")
                    for m in beat.get("messages", [])
                    if m["type"] == "tool_call_message" and m.get("tool") in ("write_file", "edit_file", "shell") and isinstance(m.get("args"), dict)
                )
                for c in beat.get("changed", []):
                    by = c.get("by") or ("agent" if c["path"] in named else "outside")
                    if by == "agent" and c["path"] not in paths:
                        paths.append(c["path"])
    return paths


def load_index():
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            index = json.load(f)
        if "head" not in index:
            index["files_changed_since_birth"] = files_changed_by_agent()
            index["head"] = None
        if "generated_tokens" not in index:
            index.pop("tokens", None)
            index["generated_tokens"] = sum(
                (b.get("usage_statistics") or {}).get("completion_tokens") or 0
                for day in index["days"]
                for b in read_jsonl(os.path.join(TRACE_DIR, f"{day}.jsonl"))
            )
        return index
    return {
        "born": None, "wakes": 0, "last": None, "dur_total_s": 0.0, "mean_dur_s": 0.0,
        "interval": {"declared": None, "mean_gap_s": None}, "gap_total_s": 0.0, "gaps": 0,
        "tools": {}, "generated_tokens": 0, "rests": 0, "diary_entries": 0, "files_changed_since_birth": [], "days": [], "exits": [],
        "head": None,
    }


def diary_count():
    try:
        return len([n for n in os.listdir(os.path.join(HOME, "diary")) if not n.startswith(".") and n.endswith((".md", ".txt"))])
    except OSError:
        return 0


def beat_entry(index, sleep_s, interval):
    entry = {"t": now_iso()}
    if os.path.exists(LAST_WAKE):
        with open(LAST_WAKE, encoding="utf-8") as f:
            wake = json.load(f)
        os.remove(LAST_WAKE)
        entry["started"] = wake.pop("t", None)
        entry.update(wake)
        entry["wake"] = index["wakes"] + 1
        index["wakes"] = entry["wake"]
        index["born"] = index["born"] or entry["t"]
        index["dur_total_s"] += wake.get("dur_s", 0)
        index["mean_dur_s"] = round(index["dur_total_s"] / index["wakes"], 1)
        for m in wake.get("messages", []):
            if m["type"] == "tool_call_message":
                index["tools"][m["tool"]] = index["tools"].get(m["tool"], 0) + 1
        index["generated_tokens"] += (wake.get("usage_statistics") or {}).get("completion_tokens") or 0
    else:
        entry["event"] = "poke-failed"
    if index["last"]:
        gap = round(stamp(entry["t"]) - stamp(index["last"]), 1)
        entry["gap_s"] = gap
        index["gaps"] += 1
        index["gap_total_s"] += gap
        index["interval"]["mean_gap_s"] = round(index["gap_total_s"] / index["gaps"], 1)
    index["last"] = entry["t"]
    index["interval"]["declared"] = interval
    entry["sleep_s"] = sleep_s
    if sleep_s > interval:
        entry["rest"] = True
        index["rests"] += 1
    head = git_home("rev-parse", "HEAD").stdout.strip() or None
    changed = attribute(changes(), index["head"], head)
    index["head"] = head
    if changed:
        entry["changed"] = changed
        for c in changed:
            if c["by"] == "agent" and c["path"] not in index["files_changed_since_birth"]:
                index["files_changed_since_birth"].append(c["path"])
    index["diary_entries"] = diary_count()
    return entry


def exit_entry(index, code):
    entry = {"t": now_iso(), "event": "loop-exit", "code": code}
    index["exits"].append({"t": entry["t"], "code": code})
    return entry


def git(*args, timeout=60):
    return subprocess.run(["git", "-C", TRACE_WORKTREE, *AUTHOR, *args], capture_output=True, text=True, timeout=timeout)


COMPACTIONS = os.path.join(TRACE_DIR, "compactions")
SUMMARIES = os.path.join(TRACE_DIR, "summaries")
BRIEFS = os.path.join(TRACE_DIR, "briefs")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize_wake(entry):
    """Append this wake's line to summaries/<day>.jsonl, given the lines of the
    wakes before it (across the day boundary)."""
    days = sorted(n for n in os.listdir(SUMMARIES) if n.endswith(".jsonl")) if os.path.isdir(SUMMARIES) else []
    previous = []
    for name in reversed(days):
        previous = read_jsonl(os.path.join(SUMMARIES, name)) + previous
        if len(previous) >= summarize.PREVIOUS_WAKES:
            break
    line = summarize.wake_line(entry, [(p["wake"], p["summary"]) for p in previous])
    if line is None:
        print(f"wake {entry['wake']}: no usable summary", file=sys.stderr)
        return
    os.makedirs(SUMMARIES, exist_ok=True)
    with open(os.path.join(SUMMARIES, f"{entry['t'][:10]}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"wake": entry["wake"], "t": entry.get("started") or entry["t"], "summary": line}, ensure_ascii=False) + "\n")


def brief_day(index, day):
    """Write briefs/<day>.md from that day's wake lines and loop events, given
    the briefs of the days before it."""
    lines = {s["wake"]: s["summary"] for s in read_jsonl(os.path.join(SUMMARIES, f"{day}.jsonl"))}
    entries = []
    for beat in read_jsonl(os.path.join(TRACE_DIR, f"{day}.jsonl")):
        t = (beat.get("started") or beat["t"])[11:16]
        if summarize.event_line(beat):
            entries.append((t, None, summarize.event_line(beat)))
        if beat.get("wake") in lines:
            entries.append((t, beat["wake"], lines[beat["wake"]]))
    prior = []
    for d in index.get("briefs", [])[-summarize.PREVIOUS_DAYS:]:
        with open(os.path.join(BRIEFS, f"{d}.md"), encoding="utf-8") as f:
            prior.append((d, f.read().strip()))
    text = summarize.day_entry(day, entries, prior)
    os.makedirs(BRIEFS, exist_ok=True)
    with open(os.path.join(BRIEFS, f"{day}.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    index.setdefault("briefs", []).append(day)


def summaries(index, entry):
    """The observatory's annotations, after the beat is recorded: a line for
    this wake, and on the first beat of a new UTC day, the brief for the day
    before it if it has lines. Either failing leaves the beat as it is."""
    if "wake" in entry:
        try:
            summarize_wake(entry)
        except Exception as e:  # noqa: BLE001 — a summary must never stall the heartbeat
            print(f"wake summary failed: {type(e).__name__}: {e}", file=sys.stderr)
    today = entry["t"][:10]
    done = set(index.get("briefs", []))
    for day in index["days"]:
        if day < today and day not in done and os.path.exists(os.path.join(SUMMARIES, f"{day}.jsonl")):
            try:
                brief_day(index, day)
            except Exception as e:  # noqa: BLE001
                print(f"daily brief failed: {type(e).__name__}: {e}", file=sys.stderr)


def compaction(entry):
    """Compact the replay if it is due, and record what changed."""
    try:
        done = compact.compact()
    except Exception as e:  # noqa: BLE001 — compaction must never stall the heartbeat
        print(f"compaction failed: {type(e).__name__}: {e}", file=sys.stderr)
        return
    if done:
        os.makedirs(COMPACTIONS, exist_ok=True)
        with open(os.path.join(COMPACTIONS, f"{entry['t'][:10]}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"wake": entry["wake"], "t": entry["t"], **done}, ensure_ascii=False) + "\n")


def main():
    if sys.argv[1] == "--exit":
        write_now("the loop has stopped", f"exit {sys.argv[2]}")
    if not os.path.isdir(TRACE_WORKTREE):
        print(f"no trace worktree at {TRACE_WORKTREE}; nothing recorded", file=sys.stderr)
        return
    os.makedirs(TRACE_DIR, exist_ok=True)
    index = load_index()
    if sys.argv[1] == "--exit":
        entry = exit_entry(index, int(sys.argv[2]))
    else:
        entry = beat_entry(index, int(sys.argv[1]), int(sys.argv[2]))
    day = entry["t"][:10]
    with open(os.path.join(TRACE_DIR, f"{day}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if day not in index["days"]:
        index["days"].append(day)
    summaries(index, entry)
    if "wake" in entry:
        compaction(entry)
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1)
    label = f"wake {entry['wake']}" if "wake" in entry else entry.get("event", "beat")
    git("add", "-A", "trace")
    commit = git("commit", "-q", "-m", label)
    if commit.returncode != 0 and "nothing to commit" not in commit.stdout + commit.stderr:
        print(f"trace commit failed: {commit.stderr.strip()}", file=sys.stderr)
        return
    push = git("push", "-q", "origin", "HEAD:trace", timeout=120)
    if push.returncode != 0:
        print(f"trace push failed (kept locally): {push.stderr.strip()[-300:]}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — the record must never stall the heartbeat
        print(f"trace failed: {type(e).__name__}: {e}", file=sys.stderr)
