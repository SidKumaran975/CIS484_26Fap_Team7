#!/usr/bin/env bash
# Start the faculty portal and student assessment with the live Babik examiner.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

exec env \
  STT_PYTHON="$ROOT_DIR/.venv/bin/python" \
  MAIN_PYTHON="$ROOT_DIR/.venv-tts/bin/python" \
  WAV2LIP_PYTHON="$ROOT_DIR/.venv-wav2lip/bin/python" \
  MEDIA_MODE=avatar \
  "$ROOT_DIR/.venv/bin/python" pipeline.py
