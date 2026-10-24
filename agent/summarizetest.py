#!/usr/bin/env python3
"""Exercises the observatory's summaries (summarize.py via trace.py) against a
stand-in for Ollama: a wake gets its line, an over-long line is asked again
once, a runaway answer is dropped instead of reaching the next wake's context,
a new UTC day gets the previous day's brief, and a dead Ollama leaves the beat
alone."""

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HOME = tempfile.mkdtemp(prefix="singulari-summary-")
os.makedirs(os.path.join(HOME, ".trace", "trace"))
os.makedirs(os.path.join(HOME, "status"))
os.environ["SINGULARI_HOME"] = HOME

REPLIES = []
REQUESTS = []


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(body)
        text = REPLIES.pop(0)
        # this model's parser puts a think-off answer in "thinking"
        msg = {"role": "assistant", "content": "", "thinking": text}
        out = json.dumps({"message": msg, "done": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *_):
        pass


server = HTTPServer(("127.0.0.1", 0), Stub)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["OLLAMA_HOST"] = f"http://127.0.0.1:{server.server_port}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trace as record  # noqa: E402


def check(name, ok, note=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + note) if note else ''}")
    if not ok:
        sys.exit(1)


def beat(n, t):
    """A beat as trace.py records it, appended to its day file the way main() does."""
    b = {"t": t, "started": t, "wake": n, "usage_statistics": {"step_count": 1},
         "messages": [{"type": "tool_call_message", "tool": "shell", "args": {"command": "ls"}},
                      {"type": "tool_return_message", "status": "success", "text": "[exit 0]"},
                      {"type": "assistant_message", "text": "Listed the directory."}]}
    with open(os.path.join(record.TRACE_DIR, f"{t[:10]}.jsonl"), "a") as f:
        f.write(json.dumps(b) + "\n")
    return b


def lines(day):
    return record.read_jsonl(os.path.join(record.SUMMARIES, f"{day}.jsonl"))


index = {"days": ["2026-01-01"], "briefs": []}
REPLIES[:] = ["Listed the directory"]
record.summaries(index, beat(1, "2026-01-01T10:00:00Z"))
check("a wake gets its line", [l["summary"] for l in lines("2026-01-01")] == ["Listed the directory"])
check("thinking off, at the agent's context size", REQUESTS[-1]["think"] is False and REQUESTS[-1]["options"]["num_ctx"] == 65536)

REPLIES[:] = [" ".join(["word"] * 20), "Listed it again"]
record.summaries(index, beat(2, "2026-01-01T10:06:00Z"))
check("over the cap, asked once more", lines("2026-01-01")[-1]["summary"] == "Listed it again")
retry = REQUESTS[-1]["messages"]
check("the retry is one fresh request quoting the long line", len(retry) == 2 and "A first try was too long" in retry[1]["content"])
check("the retry sees the earlier line", "#1 Listed the directory" in retry[1]["content"])

REPLIES[:] = [" ".join(["ramble"] * 40), " ".join(["ramble"] * 40)]
record.summaries(index, beat(3, "2026-01-01T10:12:00Z"))
check("a runaway answer is dropped", len(lines("2026-01-01")) == 2)

REPLIES[:] = ["Rested", "It was a quiet day with two wakes."]
index["days"].append("2026-01-02")
record.summaries(index, beat(4, "2026-01-02T00:03:00Z"))
brief = os.path.join(record.BRIEFS, "2026-01-01.md")
check("a new day gets the previous day's brief", os.path.exists(brief) and open(brief).read().strip() == "It was a quiet day with two wakes.")
check("the index lists it", index["briefs"] == ["2026-01-01"])
check("the brief saw that day's lines", "#2 Listed it again" in REQUESTS[-1]["messages"][1]["content"])
check("the new day's line is filed under the new day", [l["summary"] for l in lines("2026-01-02")] == ["Rested"])

os.environ["OLLAMA_HOST"] = "http://127.0.0.1:9"
import importlib  # noqa: E402
import brain  # noqa: E402

importlib.reload(brain)
before = len(lines("2026-01-02"))
record.summaries(index, beat(5, "2026-01-02T00:09:00Z"))
check("a dead Ollama writes nothing and raises nothing", len(lines("2026-01-02")) == before)
print("summaries OK")
