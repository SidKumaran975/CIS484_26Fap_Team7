#!/usr/bin/env bash
# Run from WSL; virtual environments are stored on the Linux filesystem.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_ROOT=${EXAM_ENV_ROOT:-"$HOME/.local/share/ai-oral-exam/venvs"}
STATE_ROOT=${EXAM_STATE_ROOT:-"$HOME/.local/share/ai-oral-exam"}
export PATH="$STATE_ROOT/ollama/bin:/usr/lib/wsl/lib:$PATH"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_KEEP_ALIVE=0
export OLLAMA_NO_CLOUD=1
export OLLAMA_CONTEXT_LENGTH=${OLLAMA_CONTEXT_LENGTH:-4096}
export NUM_CTX=${NUM_CTX:-2048}
export LLM_TIMEOUT=${LLM_TIMEOUT:-600}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
export STT_PYTHON=${STT_PYTHON:-"$ENV_ROOT/main/bin/python"}
export MEDIA_MODE=${MEDIA_MODE:-avatar}
export MEDIA_GENERATION_TIMEOUT=${MEDIA_GENERATION_TIMEOUT:-900}
export WAV2LIP_RESIZE_FACTOR=${WAV2LIP_RESIZE_FACTOR:-2}
export WAV2LIP_PADS=${WAV2LIP_PADS:-"0 10 0 0"}
export FACE_DET_BATCH_SIZE=${FACE_DET_BATCH_SIZE:-1}
export WAV2LIP_BATCH_SIZE=${WAV2LIP_BATCH_SIZE:-8}
export EVALUATION_MODEL=${EVALUATION_MODEL:-qwen2.5:7b}
export RAG_EMBED_MODEL=${RAG_EMBED_MODEL:-nomic-embed-text}
export FACULTY_COURSE_STORAGE=${FACULTY_COURSE_STORAGE:-"$STATE_ROOT/runtime/faculty-courses"}
export FACULTY_INDEX_STORAGE=${FACULTY_INDEX_STORAGE:-"$STATE_ROOT/runtime/faculty-indexes"}
export FACULTY_MEDIA_STORAGE=${FACULTY_MEDIA_STORAGE:-"$STATE_ROOT/runtime/faculty-media"}
export APP_DB_PATH=${APP_DB_PATH:-"$ROOT/runtime/assessment.sqlite3"}
# Use a regular rollback journal for the database edited by Windows DB Browser.
export APP_DB_JOURNAL_MODE=${APP_DB_JOURNAL_MODE:-DELETE}
# Old paths are read only during the first unified-database migration.
export SESSION_DB_PATH=${SESSION_DB_PATH:-"$STATE_ROOT/runtime/sessions.sqlite3"}
export ANALYTICS_DB_PATH=${ANALYTICS_DB_PATH:-"$STATE_ROOT/runtime/analytics.sqlite3"}
export MEDIA_DIR=${MEDIA_DIR:-"$STATE_ROOT/runtime/media"}
export RECORDINGS_DIR=${RECORDINGS_DIR:-"$STATE_ROOT/runtime/recordings"}
mkdir -p "$STATE_ROOT/logs"
ollama_pid=''
cleanup() {
    [[ -z "$ollama_pid" ]] || kill "$ollama_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
export MAIN_PYTHON=${MAIN_PYTHON:-"$ENV_ROOT/main/bin/python"}
export WAV2LIP_PYTHON=${WAV2LIP_PYTHON:-"$ENV_ROOT/wav2lip/bin/python"}
for executable in "$MAIN_PYTHON" "$WAV2LIP_PYTHON"; do
    [[ -x "$executable" ]] || { echo "Missing environment: $executable. Setup is not complete." >&2; exit 1; }
done
if "$MAIN_PYTHON" "$ROOT/scripts/check-local-ports.py"; then
    :
else
    status=$?
    [[ "$status" != 10 ]] || exit 0
    exit "$status"
fi
exec 9>"$STATE_ROOT/launcher.lock"
if ! flock -n 9; then
    echo 'Another launcher is already starting or running the system. Use its terminal and browser pages.'
    exit 0
fi
command -v ffmpeg >/dev/null || { echo 'Missing ffmpeg.' >&2; exit 1; }
for asset in text-to-speech-model/Sid.wav Wav2Lip/checkpoints/wav2lip.pth Wav2Lip/face_detection/detection/sfd/s3fd.pth; do
    [[ -s "$ROOT/$asset" ]] || { echo "Missing asset: $asset" >&2; exit 1; }
done
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ollama serve >"$STATE_ROOT/logs/ollama.log" 2>&1 &
    ollama_pid=$!
    for attempt in {1..30}; do
        curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
        sleep 1
    done
fi
"$MAIN_PYTHON" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5).close()'
for model in "${OLLAMA_MODEL:-llama3}" "$EVALUATION_MODEL" "$RAG_EMBED_MODEL"; do
    ollama show "$model" >/dev/null || { echo "Missing model. Run: ollama pull $model" >&2; exit 1; }
done
echo 'Faculty portal: http://localhost:8001/login'
echo 'Sign in at http://localhost:8001/login; student assessments run on http://localhost:8000'
cd "$ROOT"
"$STT_PYTHON" -u pipeline.py
