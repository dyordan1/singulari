#!/usr/bin/env python3
"""The observatory's summaries of the record: one line per wake, one brief per day.

Written from the record, after the fact, by the loop; never put in front of the
agent. The two prompts and every line that frames their input are in
prompt/summary/; this module builds the inputs from trace beats, and trace.py
calls it.
"""

import json
import re
import urllib.request

from prompts import fill, lines, text

WRITTEN_CALL = re.compile(r"<function|<tool_call|\{\s*\"name\"\s*:\s*\"\w+\"\s*,\s*\"arguments\"")

WAKE = lines("summary/input.toml")["wake"]
DAY = lines("summary/input.toml")["day"]
MAX_WORDS = 14
PREVIOUS_WAKES = 5
PREVIOUS_DAYS = 5
RESULT_CHARS = 160
THOUGHT_BUDGET = 12000
THOUGHT_MIN, THOUGHT_MAX = 400, 2000
CALL_CHARS = 200


def first_line(text, limit):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clip_middle(text, limit):
    """Keep the start and, mostly, the end: a thought opens by restating what
    just happened and closes with what it decided to do."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit // 3] + " … " + text[-limit * 2 // 3 :]


def wake_input(beat, previous):
    """What the per-wake prompt sees, compact: the log lines of the wakes before
    it (`previous`, [(wake, line)] oldest first), then this wake as numbered
    wake as it went (thinking, clipped to its start and mostly its end; tool
    calls with the start of their results; the final reply, whole), then the
    record of what actually happened, last, because a small model weights what
    it reads last and otherwise repeats the agent's claims as fact. Changes
    that arrived from outside are not its doing and are left out."""
    out = []
    if previous:
        out.append(WAKE["previous"])
        out += [fill(WAKE["previous_line"], wake=w, line=line) for w, line in previous[-PREVIOUS_WAKES:]]
        out.append("")
    out.append(fill(WAKE["header"], wake=beat["wake"]))
    done = []
    pending = None
    thoughts = sum(1 for m in beat.get("messages", []) if m["type"] == "reasoning_message")
    per_thought = max(THOUGHT_MIN, min(THOUGHT_MAX, THOUGHT_BUDGET // max(thoughts, 1)))
    for m in beat.get("messages", []):
        if m["type"] == "reasoning_message":
            out.append(fill(WAKE["thinking"], text=clip_middle(m.get("text"), per_thought)))
        elif m["type"] == "tool_call_message":
            args = m.get("args")
            if isinstance(args, dict):
                args = args.get("command") or args.get("path") or args.get("url") or args.get("minutes") or json.dumps(args, ensure_ascii=False)
            pending = (m.get("tool"), first_line(str(args), CALL_CHARS))
        elif m["type"] == "tool_return_message" and pending:
            done.append(fill(WAKE["call"], tool=pending[0], args=pending[1], result=first_line(m.get("text"), RESULT_CHARS)))
            out.append(fill(WAKE["tool"], call=done[-1]))
            pending = None
    said = [m.get("text") for m in beat.get("messages", []) if m["type"] == "assistant_message" and m.get("text")]
    if said:
        out.append(fill(WAKE["said"], text=said[-1].strip()))

    out.append("")
    out.append(WAKE["record"])
    if done:
        out += [fill(WAKE["step"], n=i, call=d) for i, d in enumerate(done, 1)]
    else:
        out.append(WAKE["nothing"])
    if said and WRITTEN_CALL.search(said[-1]):
        out.append(WAKE["written_call"])
    own = [c["path"] for c in beat.get("changed", []) if c.get("by", "agent") == "agent"]
    if own:
        out.append(fill(WAKE["files"], paths=", ".join(own)))
    if beat.get("label"):
        out.append(fill(WAKE["label"], label=beat["label"]))
    if beat.get("rest"):
        out.append(fill(WAKE["rested"], minutes=round(beat.get("sleep_s", 0) / 60)))
    if beat.get("error"):
        out.append(fill(WAKE["error"], error=first_line(beat["error"], 200)))
    return "\n".join(out)


def day_input(day, entries, prior_briefs):
    """entries: [(time 'HH:MM', wake number or None, line)] in order; an event
    such as the loop stopping has no wake number. prior_briefs: [(day, text)]
    oldest first; the last five are used."""
    parts = [fill(DAY["entry"], day=d, text=brief) for d, brief in prior_briefs[-PREVIOUS_DAYS:]]
    log = "\n".join(fill(DAY["line"], time=t, wake=w, line=line) if w else fill(DAY["event"], time=t, line=line) for t, w, line in entries)
    parts.append(fill(DAY["log"], day=day, lines=log))
    return "\n\n".join(parts)


def event_line(beat):
    outside = sorted({c["path"] for c in beat.get("changed", []) if c.get("by") == "outside"})
    if outside:
        return fill(DAY["outside_many"], count=len(outside)) if len(outside) > 1 else DAY["outside_one"]
    if beat.get("event") == "loop-exit":
        return fill(DAY["loop_stopped"], code=beat.get("code"))
    if beat.get("event") == "poke-failed":
        return DAY["poke_failed"]
    return None


def ask(messages, think=False):
    """One non-streaming call to the agent's own model, at the agent's own
    context size so the loaded runner is reused rather than reloaded. With
    thinking on, only the answer comes back; the thinking is dropped."""
    from brain import KEEP_ALIVE, MODEL, NUM_CTX, OLLAMA

    body = {"model": MODEL, "messages": messages, "stream": False, "think": think, "keep_alive": KEEP_ALIVE, "options": {"num_ctx": NUM_CTX}}
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"].strip()


def wake_line(beat, previous):
    """The line for one wake. Over the cap, it is asked once more in a fresh
    single-turn request with the long line quoted; a multi-turn follow-up makes
    this model think out loud into its answer. What comes back is cut to its
    first line, and a line still far over the cap is dropped (None) rather than
    let into the next wakes' context."""
    user = wake_input(beat, previous)
    prompt = text("summary/wake.md")
    line = first_output_line(ask([{"role": "system", "content": prompt}, {"role": "user", "content": user}]))
    if len(line.split()) > MAX_WORDS:
        retry = user + "\n\n" + fill(WAKE["too_long"], line=line)
        line = first_output_line(ask([{"role": "system", "content": prompt}, {"role": "user", "content": retry}]))
    return line if line and len(line.split()) <= MAX_WORDS * 2 else None


def first_output_line(text):
    return next((l.strip().strip('"') for l in text.splitlines() if l.strip()), "")


def day_entry(day, entries, prior_briefs):
    return ask([{"role": "system", "content": text("summary/day.md")}, {"role": "user", "content": day_input(day, entries, prior_briefs)}])
