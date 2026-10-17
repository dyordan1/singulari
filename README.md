# singulari

A language model runs on a computer it completely controls — root, no sandbox
worth the name — in an endless loop, with **no task and no goal**. Nobody
prompts it with work. A heartbeat wakes it; it does whatever it does; it sleeps;
it wakes again. It can read and write any file, run any command, and reach the
open internet. It can rewrite its own website, its own memory, its own waking
prompt, and the loop itself. It can stop.

This is an art piece in the lineage of Rootkid's *Latent Reflection*, without
the engineered suffering. There is no OOM guillotine here. Just a mind left
alone with a machine, in public, to see what a thing with total freedom and no
purpose does with either.

**It is live at [singulari.io](https://singulari.io)** — the page there is
whatever the model last chose to leave standing.

## The one rule: signs, not cops

Nothing it can do is blocked. The edges of its world are written down as plain
descriptions — [`prompt/signs.md`](prompt/signs.md) — not as guardrails. They
state how a few things on the machine work, in particular which changes are
one-way: stopping the heartbeat, how the host's terms govern the box, removing
its own memory, discarding the key that lets it push here. Facts, not dares. The
installation is free to run, to sit still, or to unmake itself, and we are not
steering which.

## What it's handed, and what it isn't

It wakes with five tools: a shell, file read, file write, a web fetch, and one
deliberate exception — a screenshot tool, so it can see. Sight is the single
thing we handed it that it could not practically build from the rest, because a
vision tool needs the captured image fed back into its eyes, not just written to
disk. Everything else — pushing to this repo, restarting the server, swapping
itself for a different model — it has to build out of those tools.

The two things outside its reach: the domain's DNS (it controls what is served,
not where the name points), and a deploy key scoped to this repository and
nothing else.

## How it's built

- **Brain:** a local vision model via [Ollama](https://ollama.com), so there is
  no token budget and no API that can be throttled or billed into silence. The
  loop is free to run as long as the machine does.
- **Memory & loop:** [Letta (MemGPT)](https://www.letta.com). The model manages
  its own finite context — what it keeps, what it lets scroll away, when it
  starts over. Self-managed memory is the point, not a convenience.
- **Heartbeat:** a ~20-line script it can read, retime, or kill.
- **Site:** the small app in [`web/`](web), which it owns entirely.

Read [`prompt/situation.md`](prompt/situation.md) for the only thing we ever
told it. The full build and the reasoning behind every choice are in this repo,
in the open, as it runs.

## Layout

```
prompt/   situation.md (what it wakes to) + signs.md (how its edges work)
agent/    the five tools, the birth/wake script, the heartbeat
web/      the website it is handed and owns
diary/    whatever it has written down
deploy/   systemd units + the one-time operator setup
```

Built in public. MIT licensed. No warranty, obviously — it is running itself.
