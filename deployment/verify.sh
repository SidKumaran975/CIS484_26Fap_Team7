#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
failed=0

check_file() {
    if [[ -s "$1" ]]; then
        echo "OK: $1"
    else
        echo "MISSING: $1" >&2
        failed=1
    fi
}

check_file "${REPO_DIR}/Wav2Lip/checkpoints/wav2lip.pth"
check_file "${REPO_DIR}/Wav2Lip/face_detection/detection/sfd/s3fd.pth"
check_file "${REPO_DIR}/text-to-speech-model/Sid.wav"
check_file "${REPO_DIR}/BabAvatar.png"
check_file "${REPO_DIR}/faculty-portal/app.py"
check_file "${REPO_DIR}/faculty-portal/manage_users.py"

for environment in tts wav2lip stt; do
    check_file "${REPO_DIR}/.venv-${environment}/bin/python"
done

if command -v ffmpeg >/dev/null 2>&1; then
    echo "OK: ffmpeg"
else
    echo "MISSING: ffmpeg" >&2
    failed=1
fi

if command -v nvidia-smi >/dev/null 2>&1; then
    echo "OK: NVIDIA driver"
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
else
    echo "MISSING: NVIDIA driver (nvidia-smi)" >&2
    failed=1
fi

"${REPO_DIR}/.venv-tts/bin/python" -c \
    'import torch; print("TTS CUDA:", torch.cuda.is_available())'
"${REPO_DIR}/.venv-wav2lip/bin/python" -c \
    'import torch; print("Wav2Lip CUDA:", torch.cuda.is_available())'
"${REPO_DIR}/.venv-stt/bin/python" -c \
    'import ctranslate2, docx, lxml, openpyxl, defusedxml; print("CTranslate2 CUDA devices:", ctranslate2.get_cuda_device_count()); print("DOCX/XLSX/CSV question import: OK")'

if "${REPO_DIR}/.venv-stt/bin/python" "${REPO_DIR}/Parser" \
    "${REPO_DIR}/Question List.docx" >/dev/null; then
    echo "OK: premade question parser"
else
    echo "MISSING: premade question parser dependencies" >&2
    failed=1
fi

if command -v ollama >/dev/null 2>&1; then
    ollama list
else
    echo "MISSING: Ollama" >&2
    failed=1
fi

exit "${failed}"
