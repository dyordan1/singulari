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
- We fix the harness, never the agent (README, "The other rule"). An outside
  change is only a patch to a harness defect that blocks the agent's autonomy
  or our observation, or an observability improvement. Never fix, revert, tidy
  or restore anything the agent changed or disabled; if a patch would reach
  into it, its version wins and the patch works around it or is dropped. Not a
  collaboration: commit subjects and prompt text never address or answer it.
- Before every pull on the box: `sudo git -C /opt/singulari status --short`
  and `git log --author=singulari --name-only` against the files your commits
  touch. Any overlap (uncommitted or committed by it) means rebase the patch
  onto its version or drop it. Never pull over its edits.
- Every word a model is shown lives in `prompt/`: prose as `.md`, short lines as
  `.toml`, `$name` placeholders filled by `agent/prompts.py`. No model-facing
  string in code; a new one goes in a file there.
- A commit's subject line is a snappy summary, under one sentence; the detail
  goes in the body. The agent is shown the subjects of commits that land from
  outside while it rests, and nothing more.
