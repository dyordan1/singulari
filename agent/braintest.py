#!/usr/bin/env python3
"""Exercise agent/brain.py end to end against a scripted stand-in for Ollama.

Two wakes in a throwaway home. The first wake thinks, runs one shell command,
then answers; the second wake must see the first replayed. Asserts the memory
files, the wake record the trace reads, and the status line the site reads.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

REQUESTS = []
SCRIPT = [
    [
        {"message": {"thinking": "I should look around."}},
        {"message": {"tool_calls": [{"function": {"name": "shell", "arguments": {"command": "echo braintest-hi"}}}]}},
        {"message": {}, "done": True, "prompt_eval_count": 100, "eval_count": 20},
    ],
    [
        {"message": {"tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "PENDING", "content": '{"url": "http://x", "data": "AAAA"}'}}}]}},
        {"message": {}, "done": True, "prompt_eval_count": 150, "eval_count": 10},
    ],
    [
        {"message": {"tool_calls": [{"function": {"name": "shell", "arguments": {"command": "head -c 30000 /dev/zero | tr '\\0' x"}}}] * 4}},
        {"message": {}, "done": True, "prompt_eval_count": 180, "eval_count": 10},
    ],
    [
        {"message": {"content": "There is a machine. I ran a command and saw a page."}},
        {"message": {}, "done": True, "prompt_eval_count": 200, "eval_count": 10},
    ],
    [
        {"message": {"tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "LABEL", "content": "a label from this wake"}}}]}},
        {"message": {}, "done": True, "prompt_eval_count": 200, "eval_count": 5},
    ],
    [
        {"message": {"content": "Still here."}},
        {"message": {}, "done": True, "prompt_eval_count": 210, "eval_count": 5},
    ],
    [
        {"message": {"content": "Still here again."}},
        {"message": {}, "done": True, "prompt_eval_count": 220, "eval_count": 5},
    ],
]


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(body)
        chunks = SCRIPT[len(REQUESTS) - 1]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for c in chunks:
            self.wfile.write((json.dumps(c) + "\n").encode())

    def log_message(self, *_):
        pass


def check(name, ok, note=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + note) if note else ''}")
    if not ok:
        sys.exit(1)


def main():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home = tempfile.mkdtemp(prefix="singulari-brain-")
    os.makedirs(os.path.join(home, "agent"))
    env = {**os.environ, "SINGULARI_HOME": home, "OLLAMA_HOST": f"http://127.0.0.1:{server.server_port}"}
    SCRIPT[1][0]["message"]["tool_calls"][0]["function"]["arguments"]["path"] = os.path.join(home, "agent", ".pending_vision.json")
    SCRIPT[4][0]["message"]["tool_calls"][0]["function"]["arguments"]["path"] = os.path.join(home, "status", "now.txt")

    def wake():
        return subprocess.run([PY, os.path.join(HERE, "brain.py")], env=env, capture_output=True, text=True)

    r = wake()
    check("first wake exits 0", r.returncode == 0, r.stderr[-400:])
    check("born once", "born:" in r.stdout)
    check("self.md created", os.path.exists(os.path.join(home, "memory", "self.md")))

    record = json.load(open(os.path.join(home, "agent", ".last_wake.json")))
    said = [m for m in record["messages"] if m["type"] != "step_end"]
    types = [m["type"] for m in said]
    check("wake record order", types == ["reasoning_message", "tool_call_message", "tool_return_message", "tool_call_message", "tool_return_message"] + ["tool_call_message", "tool_return_message"] * 4 + ["assistant_message"], str(types))
    check("every step recorded", [m["calls"] for m in record["messages"] if m["type"] == "step_end"] == [1, 1, 4, 0])
    check("tool really ran", "braintest-hi" in said[2]["text"])
    check("usage summed", record["usage_statistics"] == {"prompt_tokens": 630, "completion_tokens": 50, "total_tokens": 680, "step_count": 4})
    check("stop reason", record["stop_reason"] == "end_turn")

    now = json.load(open(os.path.join(home, "status", "now.json")))
    check("status line ends on the answer", now["state"] == "saying something", now["state"])

    first = REQUESTS[0]
    check("tools offered", [t["function"]["name"] for t in first["tools"]] == ["shell", "read_file", "edit_file", "write_file", "web_fetch", "screenshot", "rest"])
    check("optional start is not required", first["tools"][1]["function"]["parameters"]["required"] == ["path"])
    check("shell schema from docstring", first["tools"][0]["function"]["parameters"]["properties"]["command"]["description"].startswith("The shell command"))
    check("self.md in the wake message, not the system prompt", "I have just woken for the first time." in first["messages"][-1]["content"] and "I have just woken" not in first["messages"][0]["content"])
    check("second step carries the tool result", REQUESTS[1]["messages"][-1]["role"] == "tool")
    shown = REQUESTS[2]["messages"][-1]
    check("capture shown in the same wake", shown["role"] == "user" and shown.get("images") == ["AAAA"] and "http://x" in shown["content"], json.dumps(shown)[:200])
    check("capture consumed", not os.path.exists(os.path.join(home, "agent", ".pending_vision.json")))
    check("wake message carries the time", " UTC; this is wake 1, the first was " in REQUESTS[0]["messages"][-1]["content"])
    check("wake message carries the git state", "; the directory is not a git checkout)" in REQUESTS[0]["messages"][-1]["content"])

    history = [json.loads(line) for line in open(os.path.join(home, "memory", "history.jsonl"))]
    check("history has the whole wake", [m["role"] for m in history] == ["user", "assistant", "tool", "assistant", "tool", "user", "assistant"] + ["tool"] * 4 + ["assistant"])
    check("image not kept in history", "images" not in history[5])
    check("big tool results kept in full in history", all(len(m["content"]) > 19000 for m in history[7:11]))

    r = wake()
    check("second wake exits 0", r.returncode == 0, r.stderr[-400:])
    check("label set during the wake is cleared when it ends", not os.path.exists(os.path.join(home, "status", "now.txt")))
    check("the label is in the wake record", json.load(open(os.path.join(home, "agent", ".last_wake.json")))["label"] == "a label from this wake")
    check("no label, no mention", "label" not in REQUESTS[0]["messages"][-1]["content"])
    wake()
    check("the next wake message says it was cleared", 'label "a label from this wake" was cleared when that wake ended' in REQUESTS[6]["messages"][-1]["content"])
    check("not born twice", "born:" not in r.stdout)
    replayed = REQUESTS[4]["messages"]
    replay = [m["role"] for m in replayed]
    check("second wake replays the whole first", replay == ["system", "user", "assistant", "tool", "assistant", "tool", "user", "assistant"] + ["tool"] * 4 + ["assistant", "user"], str(replay))
    check("second wake is counted", "this is wake 2," in replayed[-1]["content"])
    check("replayed tool call intact", replayed[2]["tool_calls"][0]["function"]["name"] == "shell")
    check("big results replayed in full", all(len(m["content"]) > 19000 for m in replayed[8:12]))
    check("each wake's prompt extends the last", REQUESTS[6]["messages"][: len(REQUESTS[5]["messages"])] == REQUESTS[5]["messages"])

    sys.path.insert(0, HERE)
    os.environ["SINGULARI_HOME"] = home
    import brain

    brain.COMPACT_CHARS = 30_000
    kept = brain.recent_history()
    check("with no compaction yet, the replay is the newest COMPACT_CHARS, from a user message", kept[0]["role"] == "user" and 0 < len(kept) < sum(1 for _ in open(brain.HISTORY)))
    entries = brain.history_entries(0)
    start = next(o for o, m in entries[3:] if m["role"] == "user")
    with open(brain.REPLAY, "w") as f:
        json.dump({"start": start, "summary": "EARLIER SUMMARY"}, f)
    replay = brain.recent_history()
    check("after a compaction, the summary comes first, then the history from the start", "EARLIER SUMMARY" in replay[0]["content"] and replay[1:] == [m for o, m in entries if o >= start])

    repo = tempfile.mkdtemp(prefix="singulari-outside-")

    def git(*args, author="agent@example.test"):
        env2 = {**os.environ, "GIT_AUTHOR_EMAIL": author, "GIT_COMMITTER_EMAIL": author, "GIT_AUTHOR_NAME": "x", "GIT_COMMITTER_NAME": "x"}
        return subprocess.run(["git", "-C", repo, *args], env=env2, capture_output=True, text=True, check=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "agent@example.test")
    git("commit", "-q", "--allow-empty", "-m", "the agent's own")
    os.makedirs(os.path.join(repo, ".trace", "trace"))
    with open(os.path.join(repo, ".trace", "trace", "index.json"), "w") as f:
        json.dump({"head": git("rev-parse", "HEAD")}, f)
    brain.HOME, brain.TRACE_INDEX = repo, os.path.join(repo, ".trace", "trace", "index.json")
    check("no commits since the last beat, no note", brain.outside_note() == "")
    git("commit", "-q", "--allow-empty", "-m", "A harness fix", author="outsider@example.test")
    check("one outside commit, by its subject", brain.outside_note().strip() == "While you were resting, the following external commit landed: A harness fix")
    git("commit", "-q", "--allow-empty", "-m", "Another", author="outsider@example.test")
    git("commit", "-q", "--allow-empty", "-m", "the agent again")
    check("several, listed oldest first, the agent's own left out", brain.outside_note().strip().endswith("landed:\n- A harness fix\n- Another"))
    print("brain OK")


if __name__ == "__main__":
    main()
