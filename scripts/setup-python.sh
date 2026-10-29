#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_ROOT=${EXAM_ENV_ROOT:-"$HOME/.local/share/ai-oral-exam/venvs"}
WHEELHOUSE=${EXAM_WHEELHOUSE:-"$HOME/.local/share/ai-oral-exam/wheelhouse"}
mkdir -p "$ENV_ROOT"
for name in main wav2lip; do
    python3 -m venv "$ENV_ROOT/$name"
    "$ENV_ROOT/$name/bin/python" -m pip install --upgrade pip setuptools wheel
    cuda_source=(--index-url https://download.pytorch.org/whl/cu126)
    if [[ -f "$WHEELHOUSE/torch-2.8.0+cu126-cp310-cp310-manylinux_2_28_x86_64.whl" ]]; then
        cuda_source=(--no-index --find-links "$WHEELHOUSE")
    fi
    "$ENV_ROOT/$name/bin/python" -m pip install torch==2.8.0 torchaudio==2.8.0 "${cuda_source[@]}"
    requirements="$ROOT/setup/requirements-$name.in"
    [[ ! -f "$ROOT/setup/requirements-$name.lock.txt" ]] || requirements="$ROOT/setup/requirements-$name.lock.txt"
    "$ENV_ROOT/$name/bin/python" -m pip install -r "$requirements"
    "$ENV_ROOT/$name/bin/python" -m pip check
    "$ENV_ROOT/$name/bin/python" -m pip freeze > "$ROOT/setup/requirements-$name.lock.txt"
done
