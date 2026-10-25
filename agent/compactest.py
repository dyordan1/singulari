#!/usr/bin/env python3
"""Exercises compaction (compact.py via trace.py) against a stand-in for
Ollama: under the cap nothing happens; the first time over it, what drops out
is summarized and the replay's start moves to a user message; the next one
carries the previous summary and its starting wake; an over-long answer is
asked again once; a dead Ollama still moves the start and keeps the summary
it had; the summary comes first in the next wake's replay."""

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HOME = tempfile.mkdtemp(prefix="singulari-compact-")
os.makedirs(os.path.join(HOME, "memory"))
os.makedirs(os.path.join(HOME, "agent"))
os.makedirs(os.path.join(HOME, ".trace", "trace"))
os.makedirs(os.path.join(HOME, "status"))
os.environ["SINGULARI_HOME"] = HOME

REPLIES = []
REQUESTS = []


class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(body)
        out = json.dumps({"message": {"role": "assistant", "content": REPLIES.pop(0)}, "done": True}).encode()
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
import brain  # noqa: E402
import trace as record  # noqa: E402

brain.REPLAY_MAX_CHARS, brain.REPLAY_KEEP_CHARS = 6000, 2000


def check(name, ok, note=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + note) if note else ''}")
    if not ok:
        sys.exit(1)


def wakes(first, n):
    """n wakes as brain.py remembers them: the loop's message, a call, its result, a reply."""
    with open(brain.HISTORY, "a") as f:
        for w in range(first, first + n):
            for m in (
                {"role": "user", "content": f"(the loop wakes you; it is 2026-10-24 {w // 60:02d}:{w % 60:02d} UTC; this is wake {w}, the first was 2026-10-23 04:12 UTC)"},
                {"role": "assistant", "content": "", "thinking": "x" * 200, "tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "memory/self.md", "content": "y"}}}]},
                {"role": "tool", "tool_name": "write_file", "content": "[wrote 1 bytes to memory/self.md]"},
                {"role": "assistant", "content": "Done."},
            ):
                f.write(json.dumps({"t": 0, **m}) + "\n")


def compacted():
    path = os.path.join(record.COMPACTIONS, "2026-10-24.jsonl")
    return record.read_jsonl(path)


entry = {"t": "2026-10-24T10:00:00Z", "wake": 1}
wakes(100, 5)
REPLIES.append("<summary>FIRST SUMMARY</summary>")
record.compaction(entry)
state = brain.replay_state()
check("with no start yet, the first compaction runs", len(REQUESTS) == 1 and state["summary"] == "FIRST SUMMARY")
check("its input is the transcript and the record, no previous summary", "write_file memory/self.md" in REQUESTS[0]["messages"][1]["content"] and "previous summary" not in REQUESTS[0]["messages"][1]["content"])
check("thinking on, the agent's model", REQUESTS[0]["think"] is True and REQUESTS[0]["model"] == "singulari")
entries = brain.history_entries(state["start"])
check("the start is on a user message", entries[0][1]["role"] == "user")
check("the compaction is recorded", compacted()[-1]["summary"] == "FIRST SUMMARY")

record.compaction(entry)
check("under the cap, nothing happens", len(REQUESTS) == 1)

replay = brain.recent_history()
check("the summary comes first in the replay", "FIRST SUMMARY" in replay[0]["content"] and replay[1] == entries[0][1])
check("and the replay is the same next time", brain.recent_history() == replay)

wakes(105, 20)
REPLIES += ["<summary>" + "word " * 1200 + "</summary>", "<summary>SECOND SUMMARY</summary>"]
record.compaction(entry)
second = REQUESTS[-2]["messages"][1]["content"]
check("the next compaction carries the previous summary", "FIRST SUMMARY" in second)
check("and covers from where the previous one started", f"from wake {state['since'][0]} " in second)
check("an over-long answer is asked again once", len(REQUESTS) == 3 and "That was 1200 words" in REQUESTS[-1]["messages"][1]["content"])
check("the retry's answer is kept", brain.replay_state()["summary"] == "SECOND SUMMARY")

before = brain.replay_state()
wakes(125, 20)
server.shutdown()
server.server_close()
record.compaction(entry)
after = brain.replay_state()
check("a dead Ollama still moves the start", after["start"] > before["start"])
check("and keeps the summary it had", after["summary"] == "SECOND SUMMARY")
check("and the failure is recorded", "error" in compacted()[-1])
print("compaction OK")
