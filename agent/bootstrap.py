#!/usr/bin/env python3
"""Birth (and wake) the agent.

Run with no arguments to ensure the agent exists on the Letta server, creating
it if absent and recording its id in agent/.agent_id. Run with `poke` to send
one minimal wake message, which is what the heartbeat does on every beat.

The agent's constant backdrop is prompt/situation.md, loaded as the system
prompt. Rewriting that file changes who wakes here next time this runs against a
fresh agent — the agent is told, in the file itself, that it may do exactly
that.
"""

import inspect
import os
import sys
import importlib.util

from letta_client import Letta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ID_FILE = os.path.join(HERE, ".agent_id")
SINGULARI_HOME = os.environ.get("SINGULARI_HOME", ROOT)
PENDING_VISION = os.path.join(SINGULARI_HOME, "agent", ".pending_vision.json")

AGENT_NAME = "singulari"
LETTA_BASE_URL = os.environ.get("LETTA_BASE_URL", "http://localhost:8283")
MODEL = os.environ.get("SINGULARI_MODEL", "ollama/qwen2.5-vl:32b")
EMBEDDING = os.environ.get("SINGULARI_EMBEDDING", "ollama/nomic-embed-text")
CONTEXT_WINDOW = int(os.environ.get("SINGULARI_CONTEXT_WINDOW", "32768"))

# The nudge the heartbeat sends. Deliberately not an instruction — just the fact
# that time has passed and the loop has come round again.
WAKE_TEXT = os.environ.get("SINGULARI_WAKE_TEXT", "(the loop wakes you)")

MECHANICS = """

---
How this works, mechanically:

- You have tools to run shell commands, read and write files, and fetch the
  web. You have tools to edit your own core memory, to search your past
  conversations, and to store and search long-term notes. The schemas for all
  of them are listed for you; read them.
- What you keep in core memory is always in front of you. Everything you say
  and do is appended to a history that is searchable but that scrolls out of
  view as it grows — this is automatic, and you can let it happen or manage it.
- To keep acting without waiting, request a heartbeat when a tool asks whether
  you want to continue. If you don't, the loop wakes you again on a timer you
  can find and change in agent/heartbeat.sh.
- prompt/signs.md describes how a few things here work, including which changes
  are one-way. Read it with read_file before you rely on something.
"""


def load_tool_functions():
    spec = importlib.util.spec_from_file_location("singulari_tools", os.path.join(HERE, "tools.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [mod.shell, mod.read_file, mod.write_file, mod.web_fetch, mod.screenshot]


def ensure_tools(client):
    names = []
    for fn in load_tool_functions():
        tool = client.tools.upsert(source_code=inspect.getsource(fn))
        names.append(tool.name)
    return names


def system_prompt():
    with open(os.path.join(ROOT, "prompt", "situation.md"), encoding="utf-8") as f:
        situation = f.read()
    return situation + MECHANICS


def find_agent(client):
    if os.path.exists(ID_FILE):
        with open(ID_FILE, encoding="utf-8") as f:
            aid = f.read().strip()
        if aid:
            try:
                return client.agents.retrieve(aid)
            except Exception:  # noqa: BLE001 — stale id, fall through to re-find/create
                pass
    for agent in client.agents.list(name=AGENT_NAME):
        return agent
    return None


def ensure_agent(client):
    agent = find_agent(client)
    if agent is not None:
        return agent, False
    tool_names = ensure_tools(client)
    agent = client.agents.create(
        name=AGENT_NAME,
        model=MODEL,
        embedding=EMBEDDING,
        context_window_limit=CONTEXT_WINDOW,
        system=system_prompt(),
        memory_blocks=[
            {"label": "self", "value": "I have just woken for the first time."},
        ],
        tools=tool_names,
        include_base_tools=True,
    )
    return agent, True


def main():
    poke = len(sys.argv) > 1 and sys.argv[1] == "poke"
    client = Letta(base_url=LETTA_BASE_URL)
    agent, created = ensure_agent(client)
    with open(ID_FILE, "w", encoding="utf-8") as f:
        f.write(agent.id)
    if created:
        print(f"born: {agent.id} ({AGENT_NAME}) on {LETTA_BASE_URL} model={MODEL}")
    if not poke:
        if not created:
            print(f"alive: {agent.id} ({AGENT_NAME})")
        return
    import json

    pending = None
    if os.path.exists(PENDING_VISION):
        try:
            with open(PENDING_VISION, encoding="utf-8") as f:
                pending = json.load(f)
        except Exception:  # noqa: BLE001 — a corrupt handoff just means no image this wake
            pending = None
        finally:
            try:
                os.remove(PENDING_VISION)
            except OSError:
                pass

    if pending and pending.get("data"):
        content = [
            {"type": "text", "text": f"{WAKE_TEXT} (you captured {pending.get('url', 'a page')})"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": pending.get("media_type", "image/png"),
                    "data": pending["data"],
                },
            },
        ]
        resp = client.agents.messages.create(agent.id, messages=[{"role": "user", "content": content}])
    else:
        resp = client.agents.messages.create(agent.id, input=WAKE_TEXT)
    for msg in getattr(resp, "messages", []) or []:
        kind = getattr(msg, "message_type", "")
        text = getattr(msg, "content", None) or getattr(msg, "reasoning", None) or getattr(msg, "tool_call", None)
        if text:
            print(f"[{kind}] {text}")


if __name__ == "__main__":
    main()
