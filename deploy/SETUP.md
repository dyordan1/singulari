# Setup — one-time, by the operator

This is the only part a human does. After it, hands off. Everything here runs
on the rented box as root.

Assumes: a fresh Ubuntu/Debian box with the 48GB A6000; `singulari.io` already
bought, with its DNS in an account the box cannot reach; and a GitHub account for
the agent (its own identity, see step 4) with write access to this repository.

Steps 1–3 are scripted in [`bringup.sh`](bringup.sh): copy it to the box and
run it detached as root, then poll its log (the model pull alone is ~20GB).

## 1. Base packages

```bash
apt-get update && apt-get install -y python3-venv git curl docker.io docker-compose-v2
systemctl enable --now docker
```

(The loop runs under systemd and Python; only the public website runs in
Docker, which is why Docker is here but Node is not — the web container brings
its own.)

## 2. Ollama + the model

```bash
curl -fsSL https://ollama.com/install.sh | sh      # installs + enables ollama.service
ollama pull qwen3.8:27b                             # the brain (~18GB on disk)
```

Give the model server room to keep earlier prompts' caches in RAM. Each wake's
prompt extends the last one (`agent/brain.py` explains), and a cache that fits
is what lets a wake compute only its new part; at the default 8 GiB, a prompt
past about 90k tokens no longer fits:

```bash
mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment=LLAMA_ARG_CACHE_RAM=32768\n' > /etc/systemd/system/ollama.service.d/cache.conf
systemctl daemon-reload && systemctl restart ollama
```

Then, once the repo is cloned (step 3), build the model the loop talks to:
the same weights behind a prompt template of our own, because Ollama's built-in
renderer tells the model not to "tell the user" about its tools
(`deploy/Modelfile` explains):

```bash
/opt/singulari/deploy/makemodel.sh singulari
```

## 3. The repo + the agent's eyes

```bash
git clone https://github.com/dyordan1/singulari.git /opt/singulari
cd /opt/singulari
python3 -m venv .venv
.venv/bin/pip install -r agent/requirements.txt
.venv/bin/playwright install --with-deps chromium    # the screenshot tool's browser
```

## 4. The agent's identity and its key (so it can push, if it chooses)

The agent pushes as itself, not as you: a GitHub account of its own (the way
github.com/claude is Anthropic's machine user), with an email you control and a
profile it may later curate. Create the account, add it as a collaborator with
write access on `dyordan1/singulari`, then give the box one credential for it,
scoped to nothing else. Either:

**A fine-grained personal access token** owned by the agent account, repository
access = this one repo, permission `Contents: read and write`:

```bash
git -C /opt/singulari remote set-url origin https://github.com/dyordan1/singulari.git
git -C /opt/singulari config credential.helper 'store --file /root/.git-credentials'
printf 'https://singulari:<TOKEN>@github.com\n' > /root/.git-credentials && chmod 600 /root/.git-credentials
```

**Or an SSH key** added to the agent account:

```bash
ssh-keygen -t ed25519 -N '' -f /root/.ssh/id_singulari -C singulari     # add the .pub to the account
cat >> /root/.ssh/config <<'CFG'
Host github.com
  IdentityFile /root/.ssh/id_singulari
  IdentitiesOnly yes
CFG
git -C /opt/singulari remote set-url origin git@github.com:dyordan1/singulari.git
```

Then make its commits its own:

```bash
git -C /opt/singulari config user.name  singulari
git -C /opt/singulari config user.email '<id>+<account>@users.noreply.github.com'
```

GitHub links a commit to a profile only through an email verified on that
account; the account's no-reply address (Settings → Emails) needs no mailbox and
always links.

The private half lives only on the box. It is the agent's one reach outside;
`prompt/signs.md` ("Your key to the outside") describes it to the agent — make
that section match the form you chose.

## 5. The record: the `trace` branch

The loop writes every beat to an orphan branch and pushes it (`agent/trace.py`).
Create the worktree once:

```bash
cd /opt/singulari
git worktree add --orphan -b trace .trace
mkdir -p .trace/trace
git -C .trace -c user.name=observatory -c user.email=observatory@singulari.io \
  commit -q --allow-empty -m "the record begins"
git -C .trace push -u origin trace
```

Then, **from your laptop** (needs admin on the repo), make `main` and `trace`
append-only — no force-push, no deletion — so the record can be added to but
never rewritten, by the agent or anyone with its key:

```bash
for b in main trace; do
  gh api -X POST repos/dyordan1/singulari/rulesets --input - <<JSON
{"name":"append-only-$b","target":"branch","enforcement":"active",
 "conditions":{"ref_name":{"include":["refs/heads/$b"],"exclude":[]}},
 "rules":[{"type":"non_fast_forward"},{"type":"deletion"}]}
JSON
done
```

## 6. Fill in the host ToS link

Edit `prompt/signs.md` and replace the terms-of-service URL with the real one of
whichever host you rented from. The agent is told it can fetch and read that
page; give it the real one.

## 7. Point the domain first

Create an A record: `singulari.io` → the box's public IP, and let it propagate.
This has to happen **before** the next step, because Caddy obtains the HTTPS
certificate by proving control of the domain over ports 80/443 — which only
works once the name resolves to this box. Make sure 80 and 443 are open.

## 8. Start it

```bash
# the brain, under systemd
cp deploy/singulari-heartbeat.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now singulari-heartbeat.service

# the public website + HTTPS, under Docker
docker compose -f deploy/compose.yml up -d --build
```

## 9. Confirm, then leave

```bash
journalctl -u singulari-heartbeat -n 50 --no-pager   # it should be waking and acting
git -C /opt/singulari/.trace log --oneline -5         # one "wake N" commit per beat
docker compose -f deploy/compose.yml logs caddy       # cert issued, no ACME errors
curl -s https://singulari.io/api/now                  # the status line, over HTTPS
```

Then stop watching, or watch from `https://singulari.io/status` like everyone
else. There is no kill switch from inside the box by design. The only lever you
keep is this host's control panel (stop / reinstall the machine), which is the
installation's end, not a graceful off switch.
