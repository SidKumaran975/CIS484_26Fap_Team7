import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from faster_whisper import WhisperModel
from starlette.concurrency import run_in_threadpool

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag.analytics import AnalyticsStore
from rag.config import Settings
from rag.engine import AssessmentEngine
from rag.media import MediaGenerator

RECORDINGS_DIR = Path(
    os.environ.get("RECORDINGS_DIR", APP_DIR / "recordings")
).resolve()
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings
    app.state.analytics = AnalyticsStore(
        settings.analytics_db_path, settings.analytics_base_watts
    )
    with app.state.analytics.run("application_start") as run:
        with run.stage("assessment_engine_initialization"):
            app.state.engine = AssessmentEngine(settings)
            app.state.media = MediaGenerator(settings)
        with run.stage("whisper_model_load"):
            app.state.whisper = WhisperModel(
                os.environ.get("WHISPER_MODEL", "base.en"),
                device=os.environ.get("WHISPER_DEVICE", "cpu"),
                compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
            )
    yield
    app.state.engine.close()
    app.state.analytics.close()


app = FastAPI(title="Capstone Oral Assessment", lifespan=lifespan)


def require_admin(provided_token: str | None, settings: Settings) -> None:
    if settings.admin_token and provided_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Invalid administrator token")


def transcribe_audio(model: WhisperModel, audio_path: Path) -> str:
    segments, _ = model.transcribe(str(audio_path), language="en")
    return " ".join(segment.text.strip() for segment in segments).strip()


def add_media(response: dict, media: MediaGenerator, prompt_key: str) -> dict:
    prompt = response.get(prompt_key, "")
    try:
        response["media_url"] = media.generate(prompt) if prompt else None
        response["media_error"] = None
    except Exception as exc:  # noqa: BLE001 - convert media errors at API boundary
        if media.settings.media_mode == "avatar":
            raise RuntimeError(f"Examiner video generation failed: {exc}") from exc
        # Explicit non-avatar diagnostic modes remain usable if media fails.
        response["media_url"] = None
        response["media_error"] = str(exc)
    if media.settings.media_mode == "avatar" and not response["media_url"]:
        raise RuntimeError("Examiner video generation did not return a video")
    return response


@app.get("/")
def home():
    return FileResponse(APP_DIR / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(APP_DIR / "admin.html")


@app.get("/health")
def health():
    status = app.state.engine.status()
    return {"status": "ok", "course_ready": status.ready}


@app.get("/api/course/status")
def course_status():
    return app.state.engine.status()


@app.post("/api/course/publish")
def publish_course(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token, app.state.settings)
    try:
        with app.state.analytics.run("course_publish") as run:
            with run.stage("course_ingestion_and_indexing"):
                status = app.state.engine.publish_course()
            run.add_metric("document_count", status.document_count)
            run.add_metric("chunk_count", status.chunk_count)
            return status
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/analytics/summary")
def analytics_summary(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token, app.state.settings)
    return app.state.analytics.summary()


@app.get("/api/analytics/runs")
def analytics_runs(
    limit: int = 50,
    x_admin_token: str | None = Header(default=None),
):
    require_admin(x_admin_token, app.state.settings)
    return {"runs": app.state.analytics.recent_runs(limit)}


@app.post("/api/sessions")
def start_session():
    try:
        with app.state.analytics.run("session_start") as run:
            with run.stage("session_creation"):
                response = app.state.engine.start_session()
            run.set_context(
                session_id=response["session_id"],
                question_id=response["question_id"],
            )
            with run.stage("examiner_media"):
                return add_media(response, app.state.media, "prompt")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/answers")
async def submit_answer(
    session_id: str = Form(...),
    audio: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
):
    settings: Settings = app.state.settings
    content_type = audio.content_type or ""
    if not content_type.startswith("audio/"):
        raise HTTPException(status_code=415, detail="An audio recording is required")

    payload = await audio.read(settings.max_audio_bytes + 1)
    if len(payload) > settings.max_audio_bytes:
        raise HTTPException(status_code=413, detail="Audio recording is too large")
    if not payload:
        raise HTTPException(status_code=400, detail="Audio recording is empty")

    try:
        with app.state.analytics.run(
            "assessment_turn", session_id=session_id
        ) as run:
            run.add_metric("audio_bytes", len(payload))
            recording_path = RECORDINGS_DIR / f"{uuid.uuid4()}.webm"
            recording_path.write_bytes(payload)
            with run.stage("speech_to_text"):
                transcript = await run_in_threadpool(
                    transcribe_audio, app.state.whisper, recording_path
                )
            run.add_metric("transcript_words", len(transcript.split()))
            with run.stage("assessment_engine"):
                response = await run_in_threadpool(
                    app.state.engine.submit_response, session_id, transcript
                )
            run.set_context(question_id=response["question_id"])
            with run.stage("examiner_media"):
                response = await run_in_threadpool(
                    add_media, response, app.state.media, "next_prompt"
                )
            return response
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Assessment session not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if not settings.retain_audio:
            if "recording_path" in locals():
                recording_path.unlink(missing_ok=True)


@app.get("/api/media/{filename}")
def serve_media(filename: str):
    media_dir = app.state.settings.media_dir.resolve()
    media_path = (media_dir / filename).resolve()
    if media_path.parent != media_dir or media_path.suffix not in {".wav", ".mp4"}:
        raise HTTPException(status_code=404, detail="Media not found")
    if not media_path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    media_type = "video/mp4" if media_path.suffix == ".mp4" else "audio/wav"
    return FileResponse(media_path, media_type=media_type)
