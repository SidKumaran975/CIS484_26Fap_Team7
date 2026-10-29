#!/usr/bin/env bash
# Official release; user-local extraction, no root, no system service.
set -euo pipefail
STATE_ROOT=${EXAM_STATE_ROOT:-"$HOME/.local/share/ai-oral-exam"}
mkdir -p "$STATE_ROOT/ollama"
curl -fL --retry 3 https://github.com/ollama/ollama/releases/download/v0.40.5/ollama-linux-amd64.tar.zst -o "$STATE_ROOT/ollama/ollama.tar.zst"
printf '%s  %s\n' dc5eabc292f9949546c90a97c820f924b035e05243b0de13c7f366182562169c "$STATE_ROOT/ollama/ollama.tar.zst" | sha256sum -c -
tar --zstd -xf "$STATE_ROOT/ollama/ollama.tar.zst" -C "$STATE_ROOT/ollama"
"$STATE_ROOT/ollama/bin/ollama" --version
