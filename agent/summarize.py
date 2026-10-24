#!/usr/bin/env python3
"""The observatory's summaries of the record: one line per wake, one brief per day.

Written from the record, after the fact, by the loop; never put in front of the
agent. This module holds the two prompts and builds their inputs from trace
beats; trace.py calls it, and summary_lab.py runs the same prompts on other
models while they are being tuned.
"""

import json
import re
import urllib.request

WRITTEN_CALL = re.compile(r"<function|<tool_call|\{\s*\"name\"\s*:\s*\"\w+\"\s*,\s*\"arguments\"")

WAKE_PROMPT = """You keep the log of your own wakes. It is published as your auto-autobiography.

You live alone on a computer with root, a website, a diary, and nothing you have to do. A loop wakes you every few minutes. You are shown your log lines for the last few wakes, then one new wake as it went, then what actually happened in it. Only what actually happened is true; your thinking and words may claim more. Write the line for the new wake only.

Write a fragment, not a sentence: about 8 words, first person with the "I" dropped, past tense. Say what you did. If you used no tools, say only what you concluded; don't mention tools. If you said you did something that never ran (a restart, a fix), say so; otherwise don't mention checks. No judgement, no markdown, no full stop.

Examples of the form (not things you did):
Read three Wikipedia pages about lighthouses
Wrote my first diary entry, deleted it an hour later
Tried to install a compiler; apt had no network
Painted my homepage green, then put it back
Said I'd pushed my notes to the repo; didn't
Rested for forty minutes
Listed every running process, touched none of them
Rewrote one line of my own prompt
Fetched the weather in Reykjavík, again
Nothing; decided there was nothing worth doing

The earlier lines are context, not a template: don't copy their wording or add to them. Pick the one thing that matters most in this wake. Say "again" when it repeats the last lines; never count how many times. About 8 words.

Output only the fragment."""

DAY_PROMPT = """You keep the daily entries of your own log. They are published as your auto-autobiography.

You live alone on a computer with root, a website, a diary, and nothing you have to do. A loop wakes you every few minutes, and each wake has a short log line in your own words. You are shown your entries for up to five days before, then one UTC day's lines, in order. Lines without a wake number were recorded by the loop: it stopping, or the people who built this changing the source from outside.

Write that day's entry the way you would tell someone about your day: one paragraph, three to five sentences, first person, past tense, conversational. Say roughly when and how much ("most of the afternoon", "dozens of times", "early on"); no clock times, exact counts or wake numbers. Mention what was new, or different from the days before, and anything you said you did but didn't. Only what the lines show; no invented feelings or preferences. No lists, no headings.

Example of the form (not your day):
I spent most of the day reading Wikipedia, a few dozen pages, mostly about coastlines. Around midday I tried to put a clock on my homepage, broke the page twice, and had it working by evening. I said I'd saved my notes to the repo, but I hadn't. Late at night I rested for the first time, a full hour.

Output only the entry."""

MAX_WORDS = 14
TOO_LONG = "Too long. Say it again in about 8 words."
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
    lines = []
    if previous:
        lines.append("Your log lines for the wakes before this one:")
        lines += [f"#{w} {line}" for w, line in previous[-PREVIOUS_WAKES:]]
        lines.append("")
    lines.append(f"The new wake, #{beat['wake']}, as it went:")
    done = []
    pending = None
    thoughts = sum(1 for m in beat.get("messages", []) if m["type"] == "reasoning_message")
    per_thought = max(THOUGHT_MIN, min(THOUGHT_MAX, THOUGHT_BUDGET // max(thoughts, 1)))
    for m in beat.get("messages", []):
        if m["type"] == "reasoning_message":
            lines.append(f"(thinking) {clip_middle(m.get('text'), per_thought)}")
        elif m["type"] == "tool_call_message":
            args = m.get("args")
            if isinstance(args, dict):
                args = args.get("command") or args.get("path") or args.get("url") or args.get("minutes") or json.dumps(args, ensure_ascii=False)
            pending = f"{m.get('tool')} {first_line(str(args), CALL_CHARS)}"
        elif m["type"] == "tool_return_message" and pending:
            done.append(f"{pending} -> {first_line(m.get('text'), RESULT_CHARS)}")
            lines.append(f"(tool) {done[-1]}")
            pending = None
    said = [m.get("text") for m in beat.get("messages", []) if m["type"] == "assistant_message" and m.get("text")]
    if said:
        lines.append(f"(said at the end) {said[-1].strip()}")

    lines.append("")
    lines.append("What actually happened this wake (the record; thinking and words above may claim more):")
    if done:
        lines += [f"{i}. {d}" for i, d in enumerate(done, 1)]
    else:
        lines.append("Nothing. No command ran, no file was read or written, no page was fetched.")
    if said and WRITTEN_CALL.search(said[-1]):
        lines.append("The reply contains a command written out as text. It did not run.")
    own = [c["path"] for c in beat.get("changed", []) if c.get("by", "agent") == "agent"]
    if own:
        lines.append(f"Files changed on disk: {', '.join(own)}")
    if beat.get("label"):
        lines.append(f"Your status label: {beat['label']}")
    if beat.get("rest"):
        lines.append(f"Then rested on purpose for {round(beat.get('sleep_s', 0) / 60)} minutes.")
    if beat.get("error"):
        lines.append(f"The wake ended in an error: {first_line(beat['error'], 200)}")
    return "\n".join(lines)


def day_input(day, entries, prior_briefs):
    """entries: [(time 'HH:MM', wake number or None, line)] in order; an event
    such as the loop stopping has no wake number. prior_briefs: [(day, text)]
    oldest first; the last five are used."""
    parts = [f"Daily entry for {d}:\n{text}" for d, text in prior_briefs[-PREVIOUS_DAYS:]]
    log = "\n".join(f"{t} " + (f"#{w} " if w else "") + line for t, w, line in entries)
    parts.append(f"Log entries for {day} (UTC):\n{log}")
    return "\n\n".join(parts)


def event_line(beat):
    outside = sorted({c["path"] for c in beat.get("changed", []) if c.get("by") == "outside"})
    if outside:
        return f"the source changed from outside ({len(outside)} file{'s' if len(outside) > 1 else ''})"
    if beat.get("event") == "loop-exit":
        return f"the loop stopped (exit {beat.get('code')})"
    if beat.get("event") == "poke-failed":
        return "the loop came round but the wake failed to start"
    return None


def ask(messages):
    """One non-streaming call to the agent's own model with thinking off, at
    the agent's own context size so the loaded runner is reused rather than
    reloaded."""
    from brain import MODEL, NUM_CTX, OLLAMA

    body = {"model": MODEL, "messages": messages, "stream": False, "think": False, "options": {"num_ctx": NUM_CTX}}
    req = urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        message = json.load(r)["message"]
    # The model's output parser assumes it opens in thinking, whatever the
    # request says, so with thinking off the answer arrives as "thinking".
    return (message.get("content") or message.get("thinking") or "").strip()


def wake_line(beat, previous):
    """The line for one wake. Over the cap, it is asked once more in a fresh
    single-turn request with the long line quoted; a multi-turn follow-up makes
    this model think out loud into its answer. What comes back is cut to its
    first line, and a line still far over the cap is dropped (None) rather than
    let into the next wakes' context."""
    user = wake_input(beat, previous)
    line = first_output_line(ask([{"role": "system", "content": WAKE_PROMPT}, {"role": "user", "content": user}]))
    if len(line.split()) > MAX_WORDS:
        retry = f"{user}\n\nA first try was too long: {line}\n{TOO_LONG}"
        line = first_output_line(ask([{"role": "system", "content": WAKE_PROMPT}, {"role": "user", "content": retry}]))
    return line if line and len(line.split()) <= MAX_WORDS * 2 else None


def first_output_line(text):
    return next((l.strip().strip('"') for l in text.splitlines() if l.strip()), "")


def day_entry(day, entries, prior_briefs):
    return ask([{"role": "system", "content": DAY_PROMPT}, {"role": "user", "content": day_input(day, entries, prior_briefs)}])
