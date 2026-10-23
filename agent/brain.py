#!/usr/bin/env python3
"""One wake of the agent, straight against the local Ollama.

The agent is a model, five tools, and a folder of files that is its memory:

- memory/self.md        what it chooses to keep in front of itself, every wake
- memory/history.jsonl  every message it has sent, received or seen, appended
                        as it happens; the tail that fits the window is replayed

The system prompt is prompt/situation.md, the mechanics below, and self.md as
last written. A wake sends one short message with the time, then runs tool
calls until the model answers without one or the step cap is hit. A screenshot
is handed over by the tool as a file and placed in front of the model right
after the call, as an image. The wake is summarised to
agent/.last_wake.json for the record (agent/trace.py) and narrated step by step
to status/now.json for the website.
"""

import importlib.util
import inspect
import json
import os
import re
import time
import urllib.request

from status import STATUS_DIR, write_now

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOME = os.environ.get("SINGULARI_HOME", ROOT)
MEMORY = os.path.join(HOME, "memory")
SELF = os.path.join(MEMORY, "self.md")
HISTORY = os.path.join(MEMORY, "history.jsonl")
PENDING_VISION = os.path.join(HOME, "agent", ".pending_vision.json")
LABEL = os.path.join(STATUS_DIR, "now.txt")
CLEARED_LABEL = os.path.join(STATUS_DIR, ".cleared_label")
LAST_WAKE = os.path.join(HOME, "agent", ".last_wake.json")

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL = "qwen3-vl:32b"
NUM_CTX = 65536
HISTORY_CHARS = 60_000
REPLAY_RESULT_CHARS = 1500
CONTEXT_CHARS = 150_000
MAX_STEPS = 40

MECHANICS = f"""

---
How this works, mechanically:

- Your tools are listed for you with their schemas: a shell, file read, edit
  and write, a web fetch, a screenshot, and rest. Call them as tools. Their results come back
  to you in the same wake and you can keep calling until you are done. A wake
  ends when you answer without calling a tool, after {MAX_STEPS} steps, or when
  the window is full.
- Nobody is on the other end of these messages. The ones marked as from a user
  are the loop waking you, with the time. Everything else in the history is
  your own earlier thinking and doing.
- Your memory is a folder of files, `memory/`. `memory/self.md` is what you
  choose to keep: it is placed in front of you, below, every wake, exactly as
  you last wrote it. Edit it with write_file. `memory/history.jsonl` is
  everything you have said, done and seen, appended as it happens. The most
  recent stretch of it is replayed to you each wake; the rest stays on disk for
  you to read or search.
- prompt/signs.md describes how a few things here work, including which
  changes are one-way. Read it with read_file before you rely on something.

---
What you have kept (memory/self.md):

"""

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
    """Ollama tool schemas from each function's signature and Google-style docstring."""
    specs = []
    for name, fn in tools.items():
        doc = inspect.getdoc(fn) or ""
        description, _, rest = doc.partition("\nArgs:\n")
        args = dict(re.findall(r"^\s+(\w+): (.+)$", rest.partition("\nReturns:")[0], re.M))
        sig = inspect.signature(fn).parameters
        params = list(sig)
        required = [p for p in params if sig[p].default is inspect.Parameter.empty]
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description.strip(),
                    "parameters": {
                        "type": "object",
                        "properties": {p: {"type": "string", "description": args.get(p, "")} for p in params},
                        "required": required,
                    },
                },
            }
        )
    return specs


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def system_prompt():
    return read(os.path.join(ROOT, "prompt", "situation.md")) + MECHANICS + read(SELF)


def remember(msg):
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), **msg}) + "\n")


def recent_history():
    """The newest messages that fit the budget, with old tool results shortened
    (they were seen in full when they happened) and the cut placed on a user or
    assistant message so no tool result appears without its call."""
    if not os.path.exists(HISTORY):
        return []
    with open(HISTORY, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 4 * HISTORY_CHARS))
        chunk = f.read().decode("utf-8", errors="replace")
    lines = chunk.split("\n")
    if size > 4 * HISTORY_CHARS:
        lines = lines[1:]
    msgs = [json.loads(line) for line in lines if line.strip()]
    for m in msgs:
        m.pop("t", None)
        if m["role"] == "tool" and len(m["content"]) > REPLAY_RESULT_CHARS:
            m["content"] = m["content"][:REPLAY_RESULT_CHARS] + " [...shortened in replay...]"
    total, i = 0, len(msgs)
    while i > 0 and total <= HISTORY_CHARS:
        i -= 1
        total += len(json.dumps(msgs[i]))
    while i < len(msgs) and msgs[i]["role"] == "tool":
        i += 1
    return msgs[i:]


def show_capture(messages):
    """If a tool left a screenshot behind, put it in front of the model now."""
    if not os.path.exists(PENDING_VISION):
        return
    pending = json.loads(read(PENDING_VISION))
    os.remove(PENDING_VISION)
    shown = {"role": "user", "content": f"(the page you captured, {pending.get('url', '?')}, is in front of you)"}
    messages.append({**shown, "images": [pending["data"]]})
    remember(shown)


def chat(messages, tools):
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": tools,
        "stream": True,
        "think": True,
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
        result, status = f"[no such tool: {name}]", "error"
    else:
        try:
            result, status = str(tools[name](**args)), "success"
        except Exception as e:  # noqa: BLE001 — the model sees the failure; the wake continues
            result, status = f"[{name} failed: {type(e).__name__}: {e}]", "error"
    shown = result if len(result) <= 2000 else result[:2000] + " [...truncated...]"
    wake["messages"].append({"type": "tool_return_message", "status": status, "text": shown})
    msg = {"role": "tool", "tool_name": name, "content": result}
    messages.append(msg)
    remember(msg)
    show_capture(messages)


def main():
    if not os.path.exists(SELF):
        os.makedirs(MEMORY, exist_ok=True)
        with open(SELF, "w", encoding="utf-8") as f:
            f.write("I have just woken for the first time.\n")
        print(f"born: {MODEL}, memory at {MEMORY}")

    cleared = read(CLEARED_LABEL).strip() if os.path.exists(CLEARED_LABEL) else ""
    for stale in (CLEARED_LABEL, PENDING_VISION):
        try:
            os.remove(stale)
        except FileNotFoundError:
            pass
    tools = load_tools()
    specs = tool_specs(tools)
    messages = [{"role": "system", "content": system_prompt()}, *recent_history()]
    text = time.strftime("(the loop wakes you; it is %Y-%m-%d %H:%M UTC", time.gmtime())
    if cleared:
        text += f'; your status label "{cleared[:200]}" was cleared when that wake ended'
    first = {"role": "user", "content": text + ")"}
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
