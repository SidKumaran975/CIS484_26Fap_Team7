#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This installer is intended for the Ubuntu deployment server." >&2
    exit 1
fi

if [[ ! -w "${REPO_DIR}" ]]; then
    echo "${REPO_DIR} is not writable by $(id -un)." >&2
    echo "Run this installer as the account that owns the repository." >&2
    exit 1
fi

python3 -m venv "${REPO_DIR}/.venv-tts"
python3 -m venv "${REPO_DIR}/.venv-wav2lip"
python3 -m venv "${REPO_DIR}/.venv-stt"

"${REPO_DIR}/.venv-tts/bin/python" -m pip install --upgrade pip setuptools wheel
"${REPO_DIR}/.venv-wav2lip/bin/python" -m pip install --upgrade pip setuptools wheel
"${REPO_DIR}/.venv-stt/bin/python" -m pip install --upgrade pip setuptools wheel

# PyTorch's Linux wheels include the CUDA runtime. The installed NVIDIA driver
# must be recent enough for the runtime selected by pip.
"${REPO_DIR}/.venv-tts/bin/pip" install torch torchaudio
"${REPO_DIR}/.venv-tts/bin/pip" install -r "${REPO_DIR}/deployment/requirements-tts.txt"

"${REPO_DIR}/.venv-wav2lip/bin/pip" install torch torchvision
"${REPO_DIR}/.venv-wav2lip/bin/pip" install -r "${REPO_DIR}/deployment/requirements-wav2lip.txt"

"${REPO_DIR}/.venv-stt/bin/pip" install -r "${REPO_DIR}/deployment/requirements-stt.txt"

mkdir -p \
    "${REPO_DIR}/Wav2Lip/checkpoints" \
    "${REPO_DIR}/Wav2Lip/results" \
    "${REPO_DIR}/Wav2Lip/temp" \
    "${REPO_DIR}/speech-to-text/recordings"

echo
echo "Python environments are installed."
echo "Next steps:"
echo "  1. Install Ollama and run: ollama pull llama3"
echo "  2. Copy the two Wav2Lip weights and the private Sid.wav file."
echo "  3. Follow deployment/README.md to install the service and Nginx config."

if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi
else
    echo "WARNING: nvidia-smi was not found. Install the NVIDIA server driver."
fi
