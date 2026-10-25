#!/usr/bin/env python3
"""Exercises compaction (compact.py via trace.py) against a stand-in for
Ollama: the first compaction takes the newest COMPACT_CHARS; the replay is
then the summary alone, and grows wake by wake; under COMPACT_CHARS nothing
happens; at it, the whole replay, previous summary included, becomes the next
summary; an answer without the tags or over-long is asked again once; a dead
Ollama still starts the replay over and keeps the summary it had."""

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

brain.COMPACT_CHARS = 6000


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
wakes(100, 20)
REPLIES.append("<summary>FIRST SUMMARY</summary>")
record.compaction(entry)
state = brain.replay_state()
first = REQUESTS[0]["messages"][1]["content"]
check("with no compaction yet, the first one runs", len(REQUESTS) == 1 and state["summary"] == "FIRST SUMMARY")
check("over the newest COMPACT_CHARS of history, from a wake", "wake 100 " not in first and first.split("\n\n")[1].startswith("[the loop]") and "wake 119 " in first)
check("thinking on, the agent's model", REQUESTS[0]["think"] is True and REQUESTS[0]["model"] == "singulari")
check("everything so far is summarized: the replay is the summary alone", state["start"] == os.path.getsize(brain.HISTORY) and len(brain.recent_history()) == 1 and "FIRST SUMMARY" in brain.recent_history()[0]["content"])
check("the compaction is recorded", compacted()[-1]["summary"] == "FIRST SUMMARY")

wakes(120, 3)
record.compaction(entry)
check("under COMPACT_CHARS, nothing happens", len(REQUESTS) == 1)
replay = brain.recent_history()
check("the replay is the summary, then every message since", "FIRST SUMMARY" in replay[0]["content"] and len(replay) == 1 + 3 * 4 and "wake 120," in replay[1]["content"])
check("and the same next time", brain.recent_history() == replay)

wakes(123, 10)
REPLIES += ["<summary>" + "word " * 1200 + "</summary>", "<summary>SECOND SUMMARY</summary>"]
record.compaction(entry)
second = REQUESTS[-2]["messages"][1]["content"]
check("at COMPACT_CHARS, the whole replay is summarized: the previous summary", "FIRST SUMMARY" in second)
check("and every message since it", "wake 120," in second and "wake 132," in second)
check("covering from where the previous summary started", f"from wake {state['since'][0]} " in second)
check("an over-long answer is asked again once", len(REQUESTS) == 3 and "That was 1200 words" in REQUESTS[-1]["messages"][1]["content"])
check("the retry's answer is kept, and the replay starts over", brain.replay_state()["summary"] == "SECOND SUMMARY" and len(brain.recent_history()) == 1)
check("the request ends by asking for the summary", REQUESTS[-1]["messages"][1]["content"].rstrip().endswith("inside <summary></summary>."))

wakes(133, 12)
REPLIES += ["You're right, and I should be direct about it.", "<summary>THIRD SUMMARY</summary>"]
record.compaction(entry)
check("an answer without the tags is not kept, and is asked again once", brain.replay_state()["summary"] == "THIRD SUMMARY" and REQUESTS[-1]["messages"] == REQUESTS[-2]["messages"])

wakes(145, 12)
REPLIES += ["Sure, here is what happened.", "Happy to help."]
record.compaction(entry)
check("twice without the tags, the previous summary stays, and the replay still starts over", brain.replay_state()["summary"] == "THIRD SUMMARY" and len(brain.recent_history()) == 1)

wakes(157, 12)
server.shutdown()
server.server_close()
record.compaction(entry)
check("a dead Ollama still starts the replay over", len(brain.recent_history()) == 1)
check("and keeps the summary it had", brain.replay_state()["summary"] == "THIRD SUMMARY")
check("and the failure is recorded", "error" in compacted()[-1])
print("compaction OK")
