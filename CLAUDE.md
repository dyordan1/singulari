# singulari

The box at `/opt/singulari` is a live checkout the agent commits in, as the
GitHub account `singulari-io`. `main` and `trace` are append-only rulesets.

- Always `git pull --ff-only origin main` before committing to `main`; the agent
  pushes to it from the box whenever it chooses.
- Never rewrite history on either branch; the rulesets refuse it anyway.
- Pulling on the box, restarting the heartbeat, or touching anything under
  `/opt/singulari` while it runs is an intervention in the piece, not a deploy.
  Only the public website (`deploy/compose.yml`) is ours to redeploy.
