# CIS484 Capstone — Team 7

This repository contains a local AI oral-assessment pipeline:

1. A professor publishes questions, rubrics, and course documents.
2. Course documents are embedded locally into an on-disk Qdrant vector index.
3. The browser records an answer and Faster Whisper transcribes it.
4. Ollama retrieves evidence, evaluates the rubric, and creates a follow-up or
   advances to the next preloaded question.
5. XTTS and Wav2Lip can optionally speak each question through the avatar.

## Repository layout

- `pipeline.py` orchestrates all three stages.
- `text-to-speech-model/` contains the text-to-speech entry point.
- `Wav2Lip/` contains the vendored Wav2Lip source code.
- `speech-to-text/` contains the FastAPI server and browser interface.
- `rag/` contains course ingestion, retrieval, evaluation, and session logic.
- `course-materials/` is the professor-facing development folder.
- `faculty-portal/` contains the faculty upload and question-generation UI
  (port 8001). See `faculty-portal/README.md`.

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

## Running locally on macOS

The AI examiner video is the default question-delivery mode. Faster Whisper,
XTTS, and Wav2Lip all run locally; CUDA is optional on macOS. Install Ollama and
FFmpeg, create a local Python environment, and install the application
dependencies:

```bash
brew install ollama ffmpeg
brew services start ollama
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r deployment/requirements-stt.txt
python -m pip install torch torchaudio torchvision
python -m pip install -r deployment/requirements-tts.txt
python -m pip install -r deployment/requirements-wav2lip.txt
```

Pull the local evaluation and embedding models, start the application, then
publish the course from the `/admin` page:

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
python pipeline.py
```

The web application is served at `http://127.0.0.1:8000`. Open `/admin` to
publish course materials before beginning an assessment.

### Sprint 1 avatar behavior

The Sprint 1 XTTS voice clone and Wav2Lip examiner are connected to every
assessment turn. Avatar mode is now the default, so launch normally:

```bash
python pipeline.py
```

Avatar mode expects the private/local assets below. They are intentionally
ignored by Git and are already present on the current development Mac:

```text
BabAvatar.png
text-to-speech-model/Sid.wav
Wav2Lip/checkpoints/wav2lip.pth
Wav2Lip/face_detection/detection/sfd/s3fd.pth
```

Every preloaded question and generated follow-up must return an examiner MP4;
the student cannot begin recording until that video finishes. The page attempts
to play each new video automatically and provides a replay button when browser
autoplay rules require a click. Generated media is cached by question and asset
version in `runtime/media`, so repeated questions do not need to be rendered
again. On a Mac CPU, a new dynamic follow-up can take tens of seconds to render;
the NVIDIA server should be substantially faster. `MEDIA_MODE=none` remains an
explicit developer diagnostic override, but it is not the normal assessment
path.

## Orchestration

The application does not use LangChain. A small project-owned Python service
layer performs the orchestration directly:

1. FastAPI receives the recording and Faster Whisper transcribes it.
2. `AssessmentEngine` loads the current question and session state.
3. `CourseIndex` embeds the question and response through Ollama and searches
   the embedded Qdrant index.
4. `Evaluator` sends the rubric, response, and retrieved evidence to the local
   Qwen model and validates its structured result with Pydantic.
5. Deterministic Python rules decide whether to follow up or advance.
6. SQLite records the turn and progress.
7. In avatar mode, XTTS speaks the selected question using the reference voice,
   Wav2Lip animates `BabAvatar.png`, and the browser plays the generated MP4.

This keeps the offline path small, inspectable, and independent of a framework
whose APIs may change. LangChain could be added later, but it is not necessary
for this workflow.

## Local analytics

The `/admin` page includes an offline analytics dashboard. A run is recorded for
every course publish, assessment-session start, and student-answer turn. The
dashboard reports:

- total latency plus per-stage timing for transcription, retrieval, model
  evaluation, XTTS, and Wav2Lip;
- process CPU time and peak resident memory;
- Ollama prompt/input tokens and generated/output tokens;
- model load, prompt-evaluation, and generation timings when Ollama returns
  them;
- run success/failure, retrieved passage counts, and non-content operational
  measurements;
- estimated watt-hours per run and in aggregate.

Analytics are stored in `runtime/analytics.sqlite3`, which is ignored by Git.
The analytics tables do not duplicate student transcript text. Electricity on
macOS is estimated using `ANALYTICS_BASE_WATTS` (30 W by default). On an NVIDIA
server, GPU draw is sampled using `nvidia-smi` and added to that base estimate.
For defensible energy reporting, calibrate the base value using an external wall
meter; the built-in figure is not a utility-grade measurement.

## Offline, locally hosted stack

No cloud model API is used. After the packages and model files have been
downloaded during setup, the application can run without internet access:

- Ollama runs the local evaluation and embedding models.
- Qwen2.5 7B is Apache-2.0 licensed and performs rubric evaluation.
- Nomic Embed Text is Apache-2.0 licensed and creates document embeddings.
- Qdrant is Apache-2.0 licensed and runs as an embedded on-disk vector store.
- Faster Whisper performs local transcription.
- XTTS and Wav2Lip provide optional local question media.

The included Wav2Lip project limits its pretrained model and training-data use
to research, academic, and personal purposes. This capstone use fits that scope,
but the avatar component would need a separate licensing review before any
commercial deployment.

## Hartman 2011 Ubuntu server

The production-ready server configuration is maintained on the
`codex/ubuntu-server-deployment` branch so the existing `main` version remains
unchanged. Server installation, GPU configuration, Nginx, HTTPS, and systemd
instructions are in [`deployment/README.md`](deployment/README.md).
