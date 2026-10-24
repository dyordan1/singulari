#!/usr/bin/env bash
# Prints the exact prompts Ollama renders for a wake mid-way (system prompt,
# the wake before, the wake message, two tool calls with their results, a screenshot shown, tools,
# thinking on) and for a summary (thinking off), by capturing its requests to
# llama-server on the loopback. Ollama's renderers add text of their own that
# no API response shows. Usage: sudo rendercheck.sh <model>; waits for a rest.
set -u
model=$1
until grep -q resting /opt/singulari/status/now.json && ! pgrep -f "[b]rain.py|[t]race.py" >/dev/null; do sleep 5; done
cap=$(mktemp)
tcpdump -i lo -s 0 -U -w "$cap" "tcp and dst portrange 30000-65535 and not port 11434" >/dev/null 2>&1 &
tp=$!
sleep 1
SINGULARI_HOME=/opt/singulari /opt/singulari/.venv/bin/python3 -c '
import json, sys, urllib.request
sys.path.insert(0, "/opt/singulari/agent")
import brain
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
def call(name, **args):
    return {"function": {"name": name, "arguments": args}}
def chat(messages, think, tools=None):
    body = {"model": sys.argv[1], "stream": False, "think": think, "keep_alive": "30s",
            "options": {"num_ctx": 8192, "num_predict": 1}, "messages": messages}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=600).read()
chat([{"role": "system", "content": brain.system_prompt()},
      {"role": "user", "content": "(the loop wakes you; it is 2026-10-24 11:55 UTC; this is wake 299)"},
      {"role": "assistant", "content": "OLD SAID", "thinking": "OLD THINKING"},
      {"role": "user", "content": "(the loop wakes you; it is 2026-10-24 12:00 UTC; this is wake 300)"},
      {"role": "assistant", "content": "", "thinking": "THINKING ONE", "tool_calls": [call("shell", command="ls /opt")]},
      {"role": "tool", "tool_name": "shell", "content": "[exit 0]\nsingulari"},
      {"role": "assistant", "content": "SAID TWO", "thinking": "THINKING TWO", "tool_calls": [call("screenshot", url="https://singulari.io")]},
      {"role": "tool", "tool_name": "screenshot", "content": "captured"},
      {"role": "user", "content": "(the page you captured, https://singulari.io, is in front of you)", "images": [PNG]}],
     True, brain.tool_specs(brain.load_tools()))
chat([{"role": "system", "content": "SUMMARY SYSTEM"}, {"role": "user", "content": "SUMMARY INPUT"}], False)
' "$model"
sleep 1
kill "$tp"; wait "$tp" 2>/dev/null
python3 -c '
import json, struct, sys
raw = open(sys.argv[1], "rb").read()
data, off = b"", 24
while off < len(raw):
    caplen = struct.unpack("<I", raw[off + 8:off + 12])[0]
    pkt = raw[off + 16:off + 16 + caplen]
    off += 16 + caplen
    ip = pkt[14:]
    tcp = ip[(ip[0] & 15) * 4:]
    data += tcp[(tcp[12] >> 4) * 4:]
dec, at = json.JSONDecoder(), 0
while (at := data.find(b"{\"prompt\":", at + 1)) > 0:
    p = dec.raw_decode(data[at:].decode("utf-8", "replace"))[0]["prompt"]
    if isinstance(p, str):
        p = {"prompt_string": p}
    print("=" * 30, "images:", len(p.get("multimodal_data") or []))
    print(p["prompt_string"])
' "$cap"
rm -f "$cap"
