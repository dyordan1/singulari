#!/usr/bin/env bash
# Builds the model the loop talks to, from deploy/Modelfile and
# prompt/chat.gotmpl: the library model's GGUF blobs behind our own template
# (the Modelfile says why).
# Usage: makemodel.sh <name>   (the loop talks to "singulari")
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
froms="$(ollama show qwen3.8:27b --modelfile | grep '^FROM /')"
tmp="$(mktemp)"
awk -v froms="$froms" '/^FROM /{print froms; next} {print}' "$here/Modelfile" > "$tmp"
printf 'TEMPLATE """%s"""\n' "$(cat "$here/../prompt/chat.gotmpl")" >> "$tmp"
ollama create "$1" -f "$tmp"
rm -f "$tmp"
