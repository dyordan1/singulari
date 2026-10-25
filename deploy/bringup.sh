#!/usr/bin/env bash
# Steps 1–3 of SETUP.md, unattended. Run detached as root on a fresh Ubuntu box
# and poll the log; a network fetch retries a few times before the script gives
# up, and every step is safe to rerun.
set -eu
export DEBIAN_FRONTEND=noninteractive
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
retry() {
  for _ in 1 2 3 4 5; do "$@" && return; log "retrying: $*"; sleep 10; done
  log "gave up: $*"; exit 1
}

log "1/3 base packages"
retry apt-get update
retry apt-get install -y python3-venv git curl docker.io docker-compose-v2
systemctl enable --now docker

log "2/3 ollama + the model"
command -v ollama >/dev/null || retry sh -c 'curl -fsSL https://ollama.com/install.sh | sh'
mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment=LLAMA_ARG_CACHE_RAM=32768\n' > /etc/systemd/system/ollama.service.d/cache.conf
systemctl daemon-reload && systemctl restart ollama
retry ollama pull qwen3.8:27b

log "3/3 the repo and the agent's eyes"
[ -d /opt/singulari/.git ] || retry git clone https://github.com/dyordan1/singulari.git /opt/singulari
cd /opt/singulari
[ -x .venv/bin/python3 ] || python3 -m venv .venv
retry .venv/bin/pip install -r agent/requirements.txt
retry .venv/bin/playwright install --with-deps chromium
deploy/makemodel.sh singulari
log "done"
