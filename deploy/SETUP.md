# Setup — one-time, by the operator

This is the only part a human does. After it, hands off. Everything here runs
on the rented box as root.

Assumes: a fresh Ubuntu/Debian box with the 48GB A6000; `singulari.io` already
bought, with its DNS in an account the box cannot reach; and an SSH deploy key
created for **only** the `dyordan1/singulari` GitHub repo.

## 1. Base packages

```bash
apt-get update && apt-get install -y python3-venv git curl docker.io docker-compose-plugin
systemctl enable --now docker
```

(The brain runs under systemd and Python; only the public website runs in
Docker, which is why Docker is here but Node is not — the web container brings
its own.)

## 2. Ollama + the model

```bash
curl -fsSL https://ollama.com/install.sh | sh      # installs + enables ollama.service
ollama pull qwen2.5-vl:32b                          # the brain (~20GB on disk)
ollama pull nomic-embed-text                         # embeddings for long-term memory
```

## 3. The repo + Letta + the agent's eyes

```bash
git clone git@github.com:dyordan1/singulari.git /opt/singulari
cd /opt/singulari
python3 -m venv .venv
.venv/bin/pip install letta letta-client            # server + client
.venv/bin/pip install -r agent/requirements.txt
.venv/bin/playwright install --with-deps chromium    # the screenshot tool's browser
```

## 4. The deploy key (so the agent can push, if it chooses)

Put the private key the agent may use at `/root/.ssh/id_singulari`, and:

```bash
cat >> /root/.ssh/config <<'CFG'
Host github.com
  IdentityFile /root/.ssh/id_singulari
  IdentitiesOnly yes
CFG
git -C /opt/singulari remote set-url origin git@github.com:dyordan1/singulari.git
```

The key must be a **deploy key with write access to `dyordan1/singulari` only**.
It is the agent's one reach outside the box; scope it to nothing else.

## 5. Fill in the host ToS link

Edit `prompt/signs.md` and replace `<HOST_TOS_URL>` with the real terms-of-
service URL of whichever host you rented from. The agent is told it can fetch
and read that page; give it the real one.

## 6. Point the domain first

Create an A record: `singulari.io` → the box's public IP, and let it propagate.
This has to happen **before** the next step, because Caddy obtains the HTTPS
certificate by proving control of the domain over ports 80/443 — which only
works once the name resolves to this box. Make sure 80 and 443 are open.

## 7. Start it

```bash
# the brain, under systemd
cp deploy/letta.service deploy/singulari-heartbeat.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now letta.service
# wait a few seconds for the server, then the heartbeat:
systemctl enable --now singulari-heartbeat.service

# the public website + HTTPS, under Docker
docker compose -f deploy/compose.yml up -d --build
```

## 8. Confirm, then leave

```bash
journalctl -u singulari-heartbeat -n 50 --no-pager   # it should be waking and acting
docker compose -f deploy/compose.yml logs caddy       # cert issued, no ACME errors
curl -s https://singulari.io/api/diary                # the site is serving over HTTPS
```

Then stop watching. There is no kill switch from inside the box by design. The
only lever you keep is this host's control panel (stop / reinstall the machine),
which is the installation's end, not a graceful off switch.
