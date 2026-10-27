#!/usr/bin/env python3
"""Launch the local oral-assessment web service.

Question speech and avatar media are generated per assessment turn by the web
application instead of generating one fixed greeting during startup.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
STT_DIR = ROOT_DIR / "speech-to-text"
FACULTY_DIR = ROOT_DIR / "faculty-portal"


def component_python(variable: str, environment: str) -> str:
    """Use an explicit interpreter or the component environment when present."""
    configured = os.environ.get(variable)
    if configured:
        return configured
    candidate = ROOT_DIR / environment / "bin" / "python"
    return str(candidate) if candidate.is_file() else sys.executable


STT_PYTHON = os.environ.get("STT_PYTHON", sys.executable)
MAIN_PYTHON = component_python("MAIN_PYTHON", ".venv-tts")
WAV2LIP_PYTHON = component_python("WAV2LIP_PYTHON", ".venv-wav2lip")
STT_HOST = os.environ.get("STT_HOST", "127.0.0.1")
STT_PORT = os.environ.get("STT_PORT", "8000")
FACULTY_PORT = os.environ.get("PORT", "8001")
MEDIA_MODE = os.environ.get("MEDIA_MODE", "avatar").lower()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("pipeline")


def preflight() -> None:
    checks = [
        ("Speech-to-text Python", Path(STT_PYTHON)),
        ("FastAPI application", STT_DIR / "app.py"),
        ("Faculty portal application", FACULTY_DIR / "app.py"),
    ]
    if MEDIA_MODE in {"audio", "avatar"}:
        checks.extend(
            [
                ("Text-to-speech Python", Path(MAIN_PYTHON)),
                (
                    "Reference voice",
                    Path(
                        os.environ.get(
                            "REFERENCE_AUDIO_PATH",
                            ROOT_DIR / "text-to-speech-model" / "Sid.wav",
                        )
                    ),
                ),
            ]
        )
    if MEDIA_MODE == "avatar":
        checks.extend(
            [
                ("Wav2Lip Python", Path(WAV2LIP_PYTHON)),
                (
                    "Wav2Lip checkpoint",
                    ROOT_DIR / "Wav2Lip" / "checkpoints" / "wav2lip.pth",
                ),
                (
                    "Wav2Lip face detector",
                    ROOT_DIR / "Wav2Lip" / "face_detection" / "detection" / "sfd" / "s3fd.pth",
                ),
                ("Avatar image", ROOT_DIR / "BabAvatar.png"),
            ]
        )
    if MEDIA_MODE not in {"none", "audio", "avatar"}:
        raise SystemExit("MEDIA_MODE must be none, audio, or avatar")

    missing = [f"{label}: {path}" for label, path in checks if not path.exists()]
    if missing:
        raise SystemExit("Preflight failed:\n  " + "\n  ".join(missing))


def main() -> None:
    preflight()
    component_environment = {
        **os.environ,
        "STT_PYTHON": STT_PYTHON,
        "MAIN_PYTHON": MAIN_PYTHON,
        "WAV2LIP_PYTHON": WAV2LIP_PYTHON,
    }
    log.info("Starting assessment server at http://%s:%s", STT_HOST, STT_PORT)
    log.info("Starting faculty portal at http://%s:%s/login", STT_HOST, FACULTY_PORT)
    faculty = subprocess.Popen(
        [STT_PYTHON, "app.py"],
        cwd=FACULTY_DIR,
        env={
            **component_environment,
            "HOST": STT_HOST,
            "PORT": FACULTY_PORT,
        },
    )
    try:
        subprocess.run(
            [
                STT_PYTHON,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                STT_HOST,
                "--port",
                STT_PORT,
            ],
            cwd=STT_DIR,
            check=True,
            env=component_environment,
        )
    except KeyboardInterrupt:
        log.info("Assessment services stopped.")
    finally:
        faculty.terminate()
        try:
            faculty.wait(timeout=10)
        except subprocess.TimeoutExpired:
            faculty.kill()


if __name__ == "__main__":
    main()
