"""Checks a candidate brain model end to end on the box, in a rest: tool calls
(one, then two in a turn), thinking, vision, and a think-off summary of a real
wake. Usage: modelcheck.py <model>. Run as root with the agent's venv."""

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/singulari/agent")
os.environ.setdefault("SINGULARI_HOME", "/opt/singulari")
import brain  # noqa: E402
import summarize  # noqa: E402

MODEL = sys.argv[1]


def resting():
    now = json.load(open("/opt/singulari/status/now.json"))
    busy = subprocess.run(["pgrep", "-f", "[b]rain.py|[t]race.py"], capture_output=True).returncode == 0
    return now.get("state") == "resting" and not busy


def chat(messages, think=True, tools=None):
    while not resting():
        time.sleep(5)
    body = {"model": MODEL, "messages": messages, "stream": False, "think": think, "keep_alive": "60s", "options": {"num_ctx": 32768}}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(brain.OLLAMA + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["message"]


specs = brain.tool_specs(brain.load_tools())
m = chat([{"role": "user", "content": "List /opt with the shell tool."}], tools=specs)
print("TOOLS:", json.dumps(m.get("tool_calls")), "| thinking chars", len(m.get("thinking") or ""), "| content", repr(m.get("content")))
m = chat([{"role": "user", "content": "Rest for 30 minutes, and read the file /etc/hostname from line 1."}], tools=specs)
print("TOOLS2:", json.dumps(m.get("tool_calls")))

os.environ["SINGULARI_HOME"] = "/tmp/modelcheck-home"
brain.load_tools()["screenshot"]("https://example.com")
image = json.load(open("/tmp/modelcheck-home/agent/.pending_vision.json"))["data"]
os.environ["SINGULARI_HOME"] = "/opt/singulari"
m = chat([{"role": "user", "content": "What is the heading on this page? Five words or fewer.", "images": [image]}], think=False)
print("VISION:", repr(m.get("content")), "| thinking", repr(m.get("thinking")))

beat = next(json.loads(line) for line in open("/opt/singulari/.trace/trace/2026-10-23.jsonl") if json.loads(line).get("wake") == 21)
m = chat([{"role": "system", "content": summarize.WAKE_PROMPT}, {"role": "user", "content": summarize.wake_input(beat, [])}], think=False)
print("SUMMARY:", repr(m.get("content")), "| thinking", repr(m.get("thinking")))
