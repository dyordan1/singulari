#!/usr/bin/env python3
"""One wake of the agent, straight against the local Ollama.

The agent is a model, five tools, and a folder of files that is its memory:

- memory/self.md        what it chooses to keep in front of itself, every wake
- memory/history.jsonl  every message it has sent, received or seen, appended
                        as it happens; replayed from the last compaction

Every word the model is shown comes from prompt/ (agent/prompts.py). The system
prompt is situation.md and mechanics.md. A wake sends one message, wake.md,
with the time and self.md as last written, then runs tool calls
until the model answers without one or the step cap is hit. A screenshot is
handed over by the tool as a file and placed in front of the model right after
the call, as an image. The wake is summarised to agent/.last_wake.json for the
record (agent/trace.py) and narrated step by step to status/now.json for the
website.

The replay is the last compaction's summary, then every message since it,
exactly as first sent. When it reaches COMPACT_CHARS, agent/compact.py
summarizes all of it into a new summary and the replay starts over from that.
Between compactions each wake's prompt is the previous wake's prompt with that
wake and the new message appended, so the model server, which keeps earlier
prompts' caches in RAM, computes only what is new. That holds only while
nothing before the new part changes: anything that changes every wake
(self.md, the time) goes in the wake message.
"""

import importlib.util
import inspect
import json
import os
import subprocess
import time
import urllib.request

import prompts
from status import STATUS_DIR, write_now

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOME = os.environ.get("SINGULARI_HOME", ROOT)
MEMORY = os.path.join(HOME, "memory")
SELF = os.path.join(MEMORY, "self.md")
HISTORY = os.path.join(MEMORY, "history.jsonl")
WAKES = os.path.join(MEMORY, "wakes.json")
PENDING_VISION = os.path.join(HOME, "agent", ".pending_vision.json")
LABEL = os.path.join(STATUS_DIR, "now.txt")
CLEARED_LABEL = os.path.join(STATUS_DIR, ".cleared_label")
LAST_WAKE = os.path.join(HOME, "agent", ".last_wake.json")
REPLAY = os.path.join(HOME, "agent", ".replay.json")
TRACE_INDEX = os.path.join(HOME, ".trace", "trace", "index.json")

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = "singulari"
NUM_CTX = 262144
KEEP_ALIVE = -1
COMPACT_CHARS = 640_000
CONTEXT_CHARS = 800_000
MAX_STEPS = 40

LOOP = prompts.lines("loop.toml")

# What the website says the agent is doing while each kind of step runs.
TOOL_STATES = {
    "shell": "running a command",
    "read_file": "reading a file",
    "write_file": "writing a file",
    "edit_file": "editing a file",
    "web_fetch": "reading the web",
    "screenshot": "looking at a page",
    "rest": "deciding to rest",
}


def load_tools():
    spec = importlib.util.spec_from_file_location("singulari_tools", os.path.join(HERE, "tools.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {fn.__name__: fn for fn in (mod.shell, mod.read_file, mod.edit_file, mod.write_file, mod.web_fetch, mod.screenshot, mod.rest)}


def tool_specs(tools):
    """Ollama tool schemas: names and required arguments from each function's
    signature, the words from prompt/tools.toml."""
    words = prompts.lines("tools.toml")
    specs = []
    for name, fn in tools.items():
        sig = inspect.signature(fn).parameters
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": words[name]["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {p: {"type": "string", "description": words[name]["args"][p]} for p in sig},
                        "required": [p for p in sig if sig[p].default is inspect.Parameter.empty],
                    },
                },
            }
        )
    return specs


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def system_prompt():
    return prompts.text("situation.md") + "\n\n" + prompts.text("mechanics.md", max_steps=MAX_STEPS)


def remember(msg):
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), **msg}) + "\n")


def history_entries(start=None):
    """[(byte offset, message)] from `start`, or, with none, from far enough
    back to cover a full replay."""
    if not os.path.exists(HISTORY):
        return []
    size = os.path.getsize(HISTORY)
    entries = []
    with open(HISTORY, "rb") as f:
        if start is None or not 0 <= start <= size:
            f.seek(max(0, size - 4 * COMPACT_CHARS))
            if f.tell():
                f.readline()
        else:
            f.seek(start)
        offset = f.tell()
        for line in f:
            if line.strip():
                m = json.loads(line)
                m.pop("t", None)
                entries.append((offset, m))
            offset += len(line)
    return entries


def newest(entries):
    """The newest entries within COMPACT_CHARS, starting on a user message, so
    no tool result appears without its call."""
    k, kept = len(entries), 0
    while k > 0 and kept + len(json.dumps(entries[k - 1][1])) <= COMPACT_CHARS:
        k -= 1
        kept += len(json.dumps(entries[k][1]))
    while k < len(entries) and entries[k][1]["role"] != "user":
        k += 1
    return entries[k:]


def replay_state():
    return json.loads(read(REPLAY)) if os.path.exists(REPLAY) else None


def recent_history():
    """The replay: the last compaction's summary, then the history since it,
    as first sent. With no compaction yet, the newest COMPACT_CHARS."""
    state = replay_state()
    if state is None:
        return [m for _, m in newest(history_entries())]
    msgs = [m for _, m in history_entries(state["start"])]
    if state.get("summary"):
        msgs.insert(0, {"role": "user", "content": prompts.text("compacted.md", summary=state["summary"])})
    return msgs


def show_capture(messages):
    """If a tool left a screenshot behind, put it in front of the model now."""
    if not os.path.exists(PENDING_VISION):
        return
    pending = json.loads(read(PENDING_VISION))
    os.remove(PENDING_VISION)
    shown = {"role": "user", "content": prompts.fill(LOOP["capture_shown"], url=pending.get("url", "?"))}
    messages.append({**shown, "images": [pending["data"]]})
    remember(shown)


def chat(messages, tools):
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": tools,
        "stream": True,
        "think": True,
        "keep_alive": KEEP_ALIVE,
        "options": {"num_ctx": NUM_CTX},
    }
    req = urllib.request.Request(
        OLLAMA + "/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1800) as resp:
        for line in resp:
            if line.strip():
                yield json.loads(line)


def context_chars(messages):
    return sum(len(json.dumps({k: v for k, v in m.items() if k != "images"})) for m in messages)


def step(messages, specs, wake):
    """One model turn: stream it, narrate it, record it. Returns the tool calls."""
    thinking, content, calls = "", "", []
    done_reason = None
    for chunk in chat(messages, specs):
        m = chunk.get("message") or {}
        if m.get("thinking"):
            if not thinking:
                write_now("thinking")
            thinking += m["thinking"]
        if m.get("content"):
            if not content:
                write_now("saying something")
            content += m["content"]
        calls.extend(m.get("tool_calls") or [])
        if chunk.get("done"):
            done_reason = chunk.get("done_reason")
            usage = wake["usage_statistics"]
            usage["prompt_tokens"] += chunk.get("prompt_eval_count") or 0
            usage["completion_tokens"] += chunk.get("eval_count") or 0
    if thinking:
        wake["messages"].append({"type": "reasoning_message", "text": thinking})
    if content:
        wake["messages"].append({"type": "assistant_message", "text": content})
    wake["messages"].append({"type": "step_end", "done_reason": done_reason, "calls": len(calls)})
    reply = {"role": "assistant", "content": content}
    if thinking:
        reply["thinking"] = thinking
    if calls:
        reply["tool_calls"] = calls
    messages.append(reply)
    remember(reply)
    print(f"[assistant] {content or thinking}"[:300])
    return None if done_reason == "length" else calls


def run_tool(call, tools, messages, wake):
    fn = call.get("function") or {}
    name, args = fn.get("name") or "", fn.get("arguments") or {}
    wake["messages"].append({"type": "tool_call_message", "tool": name, "args": args})
    detail = str(args.get("command") or args.get("url") or args.get("path") or args.get("minutes") or "") if isinstance(args, dict) else ""
    write_now(TOOL_STATES.get(name, "working"), detail if name in TOOL_STATES else name)
    print(f"[tool_call] {name} {json.dumps(args)}"[:300])
    if name not in tools:
        result, status = prompts.fill(LOOP["no_such_tool"], name=name), "error"
    else:
        try:
            result, status = str(tools[name](**args)), "success"
        except Exception as e:  # noqa: BLE001 — the model sees the failure; the wake continues
            result, status = prompts.fill(LOOP["tool_failed"], name=name, error=f"{type(e).__name__}: {e}"), "error"
    shown = result if len(result) <= 2000 else result[:2000] + " [...truncated...]"
    wake["messages"].append({"type": "tool_return_message", "status": status, "text": shown})
    msg = {"role": "tool", "tool_name": name, "content": result}
    messages.append(msg)
    remember(msg)
    show_capture(messages)


def git_state():
    """The checkout's branch and whether it has uncommitted changes, as one clause."""
    r = subprocess.run(["git", "-C", HOME, "status", "--porcelain", "--branch"], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return LOOP["not_git"]
    head, *changes = r.stdout.splitlines()
    branch = head[3:].split("...")[0]
    key = "git_clean" if not changes else "git_change" if len(changes) == 1 else "git_changes"
    return prompts.fill(LOOP[key], branch=branch, count=len(changes))


def outside_commits():
    """Subjects of the commits that landed in the checkout since the last beat
    recorded its HEAD, oldest first, by anyone but the agent's own git author:
    pulls from outside while it rested."""
    if not os.path.exists(TRACE_INDEX):
        return []
    last = json.loads(read(TRACE_INDEX)).get("head")
    if not last:
        return []
    own = subprocess.run(["git", "-C", HOME, "config", "user.email"], capture_output=True, text=True, timeout=10).stdout.strip()
    r = subprocess.run(["git", "-C", HOME, "log", "--reverse", "--format=%ae%x09%s", f"{last}..HEAD"], capture_output=True, text=True, timeout=10)
    return [subject for author, _, subject in (line.partition("\t") for line in r.stdout.splitlines()) if author != own]


def outside_note():
    subjects = outside_commits()
    if len(subjects) == 1:
        return prompts.fill(LOOP["outside_one"], subject=subjects[0])
    if subjects:
        return prompts.fill(LOOP["outside_many"], subjects="\n".join(prompts.fill(LOOP["outside_line"], subject=s) for s in subjects))
    return ""


def main():
    if not os.path.exists(SELF):
        os.makedirs(MEMORY, exist_ok=True)
        with open(SELF, "w", encoding="utf-8") as f:
            f.write("I have just woken for the first time.\n")
        print(f"born: {MODEL}, memory at {MEMORY}")
    wakes = json.loads(read(WAKES)) if os.path.exists(WAKES) else {"born": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "count": 0}
    wakes["count"] += 1
    with open(WAKES, "w", encoding="utf-8") as f:
        json.dump(wakes, f)

    cleared = read(CLEARED_LABEL).strip() if os.path.exists(CLEARED_LABEL) else ""
    for stale in (CLEARED_LABEL, PENDING_VISION):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass
    tools = load_tools()
    specs = tool_specs(tools)
    messages = [{"role": "system", "content": system_prompt()}, *recent_history()]
    text = prompts.text(
        "wake.md",
        time=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        count=wakes["count"],
        born=wakes["born"],
        git=git_state(),
        label=prompts.fill(LOOP["label_cleared"], label=cleared[:200]) if cleared else "",
        outside=outside_note(),
        self=read(SELF),
    )
    first = {"role": "user", "content": text}
    messages.append(first)
    remember(first)

    wake = {
        "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "messages": [],
        "usage_statistics": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "step_count": 0},
        "stop_reason": "max_steps",
    }
    started = time.monotonic()
    write_now("waking")
    try:
        for _ in range(MAX_STEPS):
            if context_chars(messages) > CONTEXT_CHARS:
                wake["stop_reason"] = "context_full"
                break
            wake["usage_statistics"]["step_count"] += 1
            calls = step(messages, specs, wake)
            if calls is None:
                wake["stop_reason"] = "context_full"
                break
            if not calls:
                wake["stop_reason"] = "end_turn"
                break
            for call in calls:
                run_tool(call, tools, messages, wake)
    except Exception as e:  # noqa: BLE001 — record the broken wake, then fail it
        wake["error"] = f"{type(e).__name__}: {e}"[:500]
        raise
    finally:
        if os.path.exists(LABEL):
            wake["label"] = read(LABEL).strip()
            os.replace(LABEL, CLEARED_LABEL)
        usage = wake["usage_statistics"]
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        wake["dur_s"] = round(time.monotonic() - started, 1)
        with open(LAST_WAKE, "w", encoding="utf-8") as f:
            json.dump(wake, f)


if __name__ == "__main__":
    main()
