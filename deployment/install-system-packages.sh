#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script with sudo." >&2
    exit 1
fi

apt-get update
apt-get install -y \
    build-essential \
    curl \
    ffmpeg \
    git \
    libsndfile1 \
    nginx \
    python3 \
    python3-pip \
    python3-venv

echo "Base Ubuntu packages are installed."
echo "The NVIDIA driver, CUDA 12, cuDNN 9, and Ollama are separate installs."
