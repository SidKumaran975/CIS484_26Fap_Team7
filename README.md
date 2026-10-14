# CIS484 Capstone — Team 7

This repository contains a local AI assessment pipeline with three stages:

1. Text generation and speech synthesis using Ollama and XTTS v2.
2. Avatar lip synchronization using Wav2Lip.
3. Browser-based response recording and transcription using FastAPI and
   Faster Whisper.

## Repository layout

- `pipeline.py` orchestrates all three stages.
- `text-to-speech-model/` contains the text-to-speech entry point.
- `Wav2Lip/` contains the vendored Wav2Lip source code.
- `speech-to-text/` contains the FastAPI server and browser interface.

## Local-only files

Generated recordings, transcripts, audio, video, Python environments, and
downloaded model weights are excluded from Git. In particular, the Wav2Lip
checkpoint files must be downloaded separately and placed at:

```text
Wav2Lip/checkpoints/wav2lip.pth
Wav2Lip/face_detection/detection/sfd/s3fd.pth
```

The text-to-speech stage also expects a local reference recording at
`text-to-speech-model/Sid.wav`. Do not commit recordings that contain private
voice or assessment data.

## Running locally

Install the dependencies for the speech-to-text and Wav2Lip components from
their respective `requirements.txt` files. Install the text-to-speech
dependencies (`ollama`, `TTS`, `torch`, and `torchaudio`) in the environment
used for that stage. By default every stage uses the Python interpreter that
launches `pipeline.py`. To use separate environments, set `MAIN_PYTHON` and
`WAV2LIP_PYTHON` to their Python executable paths.

Start Ollama with the configured model available, then run:

```bash
python pipeline.py
```

The web application is served at `http://127.0.0.1:8000` after audio and avatar
generation complete.

## Hartman 2011 Ubuntu server

The production-ready server configuration is maintained on the
`codex/ubuntu-server-deployment` branch so the existing `main` version remains
unchanged. Server installation, GPU configuration, Nginx, HTTPS, and systemd
instructions are in [`deployment/README.md`](deployment/README.md).
