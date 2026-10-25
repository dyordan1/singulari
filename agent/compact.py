"""Compaction of the agent's replay: when it reaches COMPACT_CHARS, all of it
(the previous summary and every message since) is summarized by the agent's
own model, in its voice, and the replay starts over from that summary.

The prompts are in prompt/compact/; this module builds their input from
history messages and reads the answer back.
"""

import calendar
import json
import os
import re
import time

import brain
import summarize
from prompts import fill, lines, text

INPUT = lines("compact/input.toml")
TARGET_WORDS = 500
LOOP_CHARS = 600
RESULT_CHARS = 1500
THOUGHT_CHARS = 1200
RECORD_CHARS = 160
WAKE = re.compile(r"it is (\d{4}-\d\d-\d\d \d\d:\d\d) UTC; this is wake (\d+)")
SUMMARY = re.compile(r"<summary>(.*?)(?:</summary>|$)", re.S)


def clip(text_, limit):
    text_ = text_ or ""
    return text_ if len(text_) <= limit else text_[:limit] + " […]"


def transcript(messages):
    """History messages as plain lines: the loop's turns, the agent's thinking
    clipped to its start and end, its words and tool calls, and each result
    clipped to its start."""
    out = []
    for m in messages:
        if m["role"] == "user":
            out.append(fill(INPUT["loop"], text=clip(m["content"], LOOP_CHARS)))
        elif m["role"] == "assistant":
            if m.get("thinking"):
                out.append(fill(INPUT["thinking"], text=summarize.clip_middle(m["thinking"], THOUGHT_CHARS)))
            if m.get("content"):
                out.append(fill(INPUT["said"], text=m["content"].strip()))
            for call in m.get("tool_calls") or []:
                fn = call.get("function") or {}
                out.append(fill(INPUT["call"], tool=fn.get("name"), args=json.dumps(fn.get("arguments"), ensure_ascii=False)))
        elif m["role"] == "tool":
            out.append(fill(INPUT["result"], text=clip(m["content"], RESULT_CHARS)))
    return "\n".join(out)


def key_arg(args):
    if isinstance(args, dict):
        return str(args.get("command") or args.get("path") or args.get("url") or args.get("minutes") or json.dumps(args, ensure_ascii=False))
    return str(args)


def wakes_in(messages):
    """[(wake number, 'YYYY-MM-DD HH:MM')] from the loop's wake messages."""
    found = [WAKE.search(m["content"]) for m in messages if m["role"] == "user"]
    return [(int(w[2]), w[1]) for w in found if w]


def span(key, start, end, **values):
    minutes = round((calendar.timegm(time.strptime(end[1], "%Y-%m-%d %H:%M")) - calendar.timegm(time.strptime(start[1], "%Y-%m-%d %H:%M"))) / 60)
    return fill(INPUT[key], last=end[0], last_time=end[1], hours=minutes // 60, minutes=minutes % 60, **values)


def record(messages, since=None):
    """What actually ran, built from the calls and their results: the span of
    wakes (and, with `since`, the whole stretch the new summary covers), then
    each distinct call with how often it ran and what came back."""
    wakes = wakes_in(messages)
    out = [INPUT["record"]]
    if wakes:
        out.append(span("span", wakes[0], wakes[-1], first=wakes[0][0], first_time=wakes[0][1]))
        if since:
            out.append(span("covers", tuple(since), wakes[-1], since=since[0], since_time=since[1]))
    pending, runs = [], {}
    for m in messages:
        if m["role"] == "assistant":
            pending += [(c.get("function") or {}) for c in m.get("tool_calls") or []]
        elif m["role"] == "tool" and pending:
            fn = pending.pop(0)
            call = f"{fn.get('name')} {clip(key_arg(fn.get('arguments')), 200)}"
            runs.setdefault(call, []).append(" ".join((m["content"] or "").split()))
    if not runs:
        out.append(INPUT["nothing_ran"])
    for call, results in runs.items():
        n = len(results)
        times = INPUT["once"] if n == 1 else fill(INPUT["times"], n=n)
        out.append(fill(INPUT["ran"], call=call, times=times))
        out.append(fill(INPUT["result_seen"], label="result" if n == 1 else "last result", result=clip(results[-1], RECORD_CHARS)))
    out.append(INPUT["nothing_else"])
    return "\n".join(out)


def request(previous, messages, since=None):
    """The system prompt and the user turn for one compaction: the messages,
    then the previous summary, then the record, last, because a small model
    weights what it reads last and otherwise repeats the agent's claims."""
    parts = [INPUT["dropping"], transcript(messages)]
    if previous:
        parts.append(fill(INPUT["previous"], summary=previous))
    parts += [record(messages, since), INPUT["ask"]]
    return text("compact/system.md"), "\n\n".join(parts)


def summary_of(answer):
    """The text inside <summary>; an answer without the tags is not a summary
    (a model that lost the instruction answers as if someone had asked)."""
    m = SUMMARY.search(answer or "")
    return m.group(1).strip() if m else ""


def compaction(previous, messages, ask, since=None):
    """The new summary, or None. `since` is (wake, time) where the previous
    summary starts. `ask(system, user)` returns the model's answer.
    Without the tags it is asked once more; over twice the target, once more
    with the word count; still wrong, nothing is kept."""
    system, user = request(previous, messages, since)
    summary = summary_of(ask(system, user))
    words = len(summary.split())
    if not summary:
        summary = summary_of(ask(system, user))
    elif words > TARGET_WORDS * 2:
        summary = summary_of(ask(system, user + "\n\n" + fill(INPUT["too_long"], words=words)))
    return summary if summary and len(summary.split()) <= TARGET_WORDS * 2 else None


def compact():
    """After a wake: when the replay (the last summary plus every message since
    it) reaches COMPACT_CHARS, summarize all of it into a new summary and start
    the replay over from that summary. A failed summary keeps the previous one
    and still starts over, so the replay stays bounded. With no compaction yet,
    the first takes the newest COMPACT_CHARS of history. Returns what changed,
    for the record, or None."""
    state = brain.replay_state()
    entries = brain.history_entries(state["start"]) if state else brain.newest(brain.history_entries())
    if not entries:
        return None
    previous = state.get("summary") if state else None
    if state and len(previous or "") + sum(len(json.dumps(m)) for _, m in entries) < brain.COMPACT_CHARS:
        return None
    messages = [m for _, m in entries]
    since = state.get("since") if previous else (wakes_in(messages) or [None])[0]
    record = {"from": entries[0][0]}
    try:
        summary = compaction(previous, messages, lambda system, user: summarize.ask([{"role": "system", "content": system}, {"role": "user", "content": user}], think=True), since if previous else None)
    except Exception as e:  # noqa: BLE001 — the replay must stay bounded whatever the model does
        summary, record["error"] = None, f"{type(e).__name__}: {e}"[:300]
    new = {"start": os.path.getsize(brain.HISTORY), "summary": summary or previous, "since": since if summary or previous else None}
    tmp = brain.REPLAY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False)
    os.replace(tmp, brain.REPLAY)
    return {**record, "to": new["start"], "summary": summary}
