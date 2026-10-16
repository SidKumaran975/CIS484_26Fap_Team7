import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from faster_whisper import WhisperModel
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag.analytics import AnalyticsStore
from rag.config import Settings
from rag.faculty import (
    FacultyAssessmentManager,
    current_portal_user,
    list_published_exams,
    require_portal_student,
    require_portal_user,
)
from rag.media import MediaGenerator

RECORDINGS_DIR = Path(
    os.environ.get("RECORDINGS_DIR", APP_DIR / "recordings")
).resolve()
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
FACULTY_PORT = int(os.environ.get("PORT", "8001"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings
    app.state.analytics = AnalyticsStore(
        settings.analytics_db_path, settings.analytics_base_watts
    )
    with app.state.analytics.run("application_start") as run:
        with run.stage("assessment_engine_initialization"):
            app.state.manager = FacultyAssessmentManager(settings)
            app.state.media = MediaGenerator(settings)
        with run.stage("whisper_model_load"):
            app.state.whisper = WhisperModel(
                os.environ.get("WHISPER_MODEL", "base.en"),
                device=os.environ.get("WHISPER_DEVICE", "cpu"),
                compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
            )
    yield
    app.state.manager.close()
    app.state.analytics.close()


app = FastAPI(title="Capstone Oral Assessment", lifespan=lifespan)


def require_admin(provided_token: str | None, settings: Settings) -> None:
    if settings.admin_token and provided_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Invalid administrator token")


def transcribe_audio(model: WhisperModel, audio_path: Path) -> str:
    segments, _ = model.transcribe(str(audio_path), language="en")
    return " ".join(segment.text.strip() for segment in segments).strip()


def add_media(response: dict, media: MediaGenerator, prompt_key: str) -> dict:
    if response.get("completed"):
        response["media_url"] = None
        response["media_error"] = None
        return response
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


def faculty_portal_url(request: Request, path: str = "/") -> str:
    return f"{request.url.scheme}://{request.url.hostname}:{FACULTY_PORT}{path}"


@app.get("/")
def home(request: Request):
    user = current_portal_user(request)
    if not user:
        return RedirectResponse(faculty_portal_url(request, "/login"), status_code=303)
    if user["role"] != "student":
        return RedirectResponse(faculty_portal_url(request), status_code=303)
    return FileResponse(APP_DIR / "index.html")


@app.get("/admin")
def admin_page(request: Request):
    return RedirectResponse(
        f"{request.url.scheme}://{request.url.hostname}:{FACULTY_PORT}/",
        status_code=303,
    )


@app.get("/health")
def health():
    try:
        exams = list_published_exams()
    except HTTPException:
        exams = []
    settings: Settings = app.state.settings
    return {
        "status": "ok",
        "published_exams": len(exams),
        "media_mode": settings.media_mode,
        "avatar_enabled": settings.media_mode == "avatar",
    }


@app.get("/api/course/status")
def course_status(_user: dict = Depends(require_portal_student)):
    exams = list_published_exams()
    return {"ready": bool(exams), "published_exams": len(exams),
            "message": "Published exams are ready." if exams else "A faculty member must publish an exam first."}


@app.post("/api/course/publish")
def publish_course(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token, app.state.settings)
    raise HTTPException(410, "Course indexing now happens from the faculty portal.")


@app.get("/api/analytics/summary")
def analytics_summary(user: dict = Depends(require_portal_user)):
    if user["role"] != "faculty":
        raise HTTPException(status_code=403, detail="Faculty only")
    return app.state.analytics.summary()


@app.get("/api/analytics/runs")
def analytics_runs(
    limit: int = 50,
    user: dict = Depends(require_portal_user),
):
    if user["role"] != "faculty":
        raise HTTPException(status_code=403, detail="Faculty only")
    return {"runs": app.state.analytics.recent_runs(limit)}


class StartSessionRequest(BaseModel):
    exam_id: str


@app.get("/api/exams")
def published_exams(_user: dict = Depends(require_portal_student)):
    return {"exams": list_published_exams()}


@app.post("/api/sessions")
def start_session(body: StartSessionRequest, _user: dict = Depends(require_portal_student)):
    engine = None
    try:
        engine = app.state.manager.engine_for_exam(body.exam_id)
        with app.state.analytics.run("session_start") as run:
            with run.stage("session_creation"):
                response = engine.start_session()
            run.add_metric("exam_id", body.exam_id)
            run.add_metric("course_id", engine.assessment.course_id)
            run.set_context(
                session_id=response["session_id"],
                question_id=response["question_id"],
            )
            with run.stage("examiner_media"):
                return add_media(response, app.state.media, "prompt")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Published exam not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if engine is not None:
            engine.close()


@app.post("/api/answers")
async def submit_answer(
    session_id: str = Form(...),
    audio: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
    _user: dict = Depends(require_portal_student),
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
        engine = None
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
                engine = app.state.manager.engine_for_session(session_id)
                run.add_metric("exam_id", engine.exam_id)
                run.add_metric("course_id", engine.assessment.course_id)
                response = await run_in_threadpool(
                    engine.submit_response, session_id, transcript
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
        if engine is not None:
            engine.close()
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
