#!/usr/bin/env python3
"""
pipeline.py — Capstone Orchestration Pipeline
===============================================
Sequentially executes:
  Stage 1 ▸ text-to-speech-model/run_voice.py   (Ollama + XTTS v2)
  Stage 2 ▸ Wav2Lip/inference.py                 (lip-sync avatar)
  Stage 3 ▸ speech-to-text/app.py                (FastAPI transcription server)

Each stage runs in its own Python virtual environment via subprocess.
If any stage fails, execution halts with the full stderr dump.
"""

import logging
import os
import shutil
import subprocess
import sys
import time

# ────────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Python interpreters. Each stage can use an isolated environment.
VENV_MAIN = os.environ.get("MAIN_PYTHON", sys.executable)
VENV_WAV2LIP = os.environ.get("WAV2LIP_PYTHON", sys.executable)
VENV_STT = os.environ.get("STT_PYTHON", VENV_MAIN)

# Stage 1 — Text-to-Speech
TTS_SCRIPT = os.path.join(ROOT_DIR, "text-to-speech-model", "run_voice.py")
TTS_CWD = os.path.join(ROOT_DIR, "text-to-speech-model")
# run_voice.py writes its output to cwd-relative "output_response.wav"
TTS_OUTPUT = os.path.join(TTS_CWD, "output_response.wav")

# Stage 2 — Wav2Lip
WAV2LIP_SCRIPT = os.path.join(ROOT_DIR, "Wav2Lip", "inference.py")
WAV2LIP_CWD = os.path.join(ROOT_DIR, "Wav2Lip")
CHECKPOINT = os.path.join(WAV2LIP_CWD, "checkpoints", "wav2lip.pth")
FACE_IMAGE = os.path.join(ROOT_DIR, "BabAvatar.png")
LIPSYNC_OUTFILE = os.path.join(WAV2LIP_CWD, "results", "result_voice.mp4")

# Stage 3 — Speech-to-Text
STT_SCRIPT = os.path.join(ROOT_DIR, "speech-to-text", "app.py")
STT_CWD = os.path.join(ROOT_DIR, "speech-to-text")
STT_HOST = os.environ.get("STT_HOST", "127.0.0.1")
STT_PORT = os.environ.get("STT_PORT", "8000")

# ────────────────────────────────────────────────────────────────
# LOGGING
# ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


# ────────────────────────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────────────────────────
def run_stage(label: str, cmd: list[str], cwd: str) -> None:
    """Run a subprocess; halt on non-zero exit."""
    log.info("━" * 60)
    log.info("▶  %s", label)
    log.info("   cmd  : %s", " ".join(cmd))
    log.info("   cwd  : %s", cwd)
    log.info("━" * 60)

    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )

    # Stream stdout for visibility
    if result.stdout:
        for line in result.stdout.splitlines():
            log.info("   [stdout] %s", line)

    if result.returncode != 0:
        log.error("✖  %s FAILED  (exit code %d)", label, result.returncode)
        if result.stderr:
            log.error("── stderr ──────────────────────────────────────")
            for line in result.stderr.splitlines():
                log.error("   %s", line)
            log.error("────────────────────────────────────────────────")
        sys.exit(result.returncode)

    log.info("✔  %s completed successfully.", label)


def verify_file(filepath: str, description: str) -> None:
    """Assert that a file exists and is non-empty."""
    if not os.path.isfile(filepath):
        log.error("✖  Verification failed — %s not found: %s", description, filepath)
        sys.exit(1)
    size = os.path.getsize(filepath)
    if size == 0:
        log.error("✖  Verification failed — %s is empty (0 bytes): %s", description, filepath)
        sys.exit(1)
    log.info("✔  Verified %s exists (%s bytes): %s", description, f"{size:,}", filepath)


# ────────────────────────────────────────────────────────────────
# PREFLIGHT CHECKS
# ────────────────────────────────────────────────────────────────
def preflight() -> None:
    """Validate that all required files and interpreters exist."""
    log.info("Running preflight checks …")

    errors: list[str] = []

    for label, path in [
        ("Main venv Python", VENV_MAIN),
        ("Wav2Lip venv Python", VENV_WAV2LIP),
        ("Speech-to-text venv Python", VENV_STT),
        ("TTS script", TTS_SCRIPT),
        ("Wav2Lip script", WAV2LIP_SCRIPT),
        ("Wav2Lip checkpoint", CHECKPOINT),
        ("Avatar image", FACE_IMAGE),
        ("STT script", STT_SCRIPT),
    ]:
        if not os.path.exists(path):
            errors.append(f"  ✖ {label}: {path}")

    if errors:
        log.error("Preflight failed — missing files:")
        for e in errors:
            log.error(e)
        sys.exit(1)

    log.info("✔  All preflight checks passed.\n")


# ────────────────────────────────────────────────────────────────
# PIPELINE STAGES
# ────────────────────────────────────────────────────────────────
def stage_1_tts() -> None:
    """Generate AI speech using Ollama + XTTS v2."""
    run_stage(
        label="Stage 1 — Text-to-Speech (Ollama + XTTS v2)",
        cmd=[VENV_MAIN, TTS_SCRIPT],
        cwd=TTS_CWD,
    )
    verify_file(TTS_OUTPUT, "TTS audio (output_response.wav)")


def stage_2_wav2lip() -> None:
    """Create a talking-face video with Wav2Lip."""
    # Ensure the results directory exists
    os.makedirs(os.path.join(WAV2LIP_CWD, "results"), exist_ok=True)
    os.makedirs(os.path.join(WAV2LIP_CWD, "temp"), exist_ok=True)

    run_stage(
        label="Stage 2 — Wav2Lip (lip-sync avatar)",
        cmd=[
            VENV_WAV2LIP,
            WAV2LIP_SCRIPT,
            "--checkpoint_path", CHECKPOINT,
            "--face", FACE_IMAGE,
            "--audio", TTS_OUTPUT,
            "--outfile", LIPSYNC_OUTFILE,
        ],
        cwd=WAV2LIP_CWD,
    )
    verify_file(LIPSYNC_OUTFILE, "lip-synced video (result_voice.mp4)")


def stage_3_stt() -> None:
    """Copy the avatar video into the web directory, then launch the server."""
    # ── Bridge: make the Wav2Lip video available to the web server ──
    web_video = os.path.join(STT_CWD, "avatar_question.mp4")
    log.info("Copying avatar video → %s", web_video)
    shutil.copy2(LIPSYNC_OUTFILE, web_video)
    verify_file(web_video, "avatar video for web server")

    log.info("━" * 60)
    log.info("▶  Stage 3 — Speech-to-Text server (FastAPI + Whisper)")
    log.info("   The server will start at http://%s:%s", STT_HOST, STT_PORT)
    log.info("   Press Ctrl+C to stop the pipeline.")
    log.info("━" * 60)

    try:
        subprocess.run(
            [
                VENV_STT, "-m", "uvicorn",
                "app:app",
                "--host", STT_HOST,
                "--port", STT_PORT,
            ],
            cwd=STT_CWD,
            check=True,
        )
    except KeyboardInterrupt:
        log.info("\n⏹  Server stopped by user (Ctrl+C).")


# ────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("=" * 60)
    log.info("  CAPSTONE ORCHESTRATION PIPELINE")
    log.info("=" * 60)
    start = time.time()

    preflight()
    stage_1_tts()
    stage_2_wav2lip()

    elapsed = time.time() - start
    log.info("")
    log.info("═" * 60)
    log.info("  Stages 1–2 completed in %.1f seconds.", elapsed)
    log.info("  Launching Stage 3 (web server) …")
    log.info("═" * 60)

    stage_3_stt()


if __name__ == "__main__":
    main()
