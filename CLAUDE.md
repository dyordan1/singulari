# singulari

The box at `/opt/singulari` is a live checkout the agent commits in, as the
GitHub account `singulari-io`. `main` and `trace` are append-only rulesets.

- Always `git pull --ff-only origin main` before committing to `main`; the agent
  pushes to it from the box whenever it chooses.
- Never rewrite history on either branch; the rulesets refuse it anyway.
- Everything on the box, the website included, is the agent's to run. We change
  the source occasionally (a harness fix), push to `main`, and pull once on the
  box; that is the whole extent of it. Never restart its services or touch its
  files there by hand.
- Every word a model is shown lives in `prompt/`: prose as `.md`, short lines as
  `.toml`, `$name` placeholders filled by `agent/prompts.py`. No model-facing
  string in code; a new one goes in a file there.
