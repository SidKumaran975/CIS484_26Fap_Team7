import os
import sys
import uuid
import shutil
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
from rag.recordings import FullRecordingStore, timestamp

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


def add_media(response: dict, media: MediaGenerator, prompt_key: str, examiner: dict | None = None) -> dict:
    if response.get("completed"):
        response["media_url"] = None
        response["media_error"] = None
        return response
    prompt = response.get(prompt_key, "")
    try:
        response["media_url"] = media.generate(prompt, examiner=examiner) if prompt else None
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


@app.get('/session-recording.js')
def recording_script():
    return FileResponse(APP_DIR / 'session-recording.js', media_type='text/javascript')


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
def start_session(body: StartSessionRequest, user: dict = Depends(require_portal_student)):
    engine = None
    try:
        engine = app.state.manager.engine_for_exam(body.exam_id)
        with app.state.analytics.run("session_start") as run:
            with run.stage("session_creation"):
                response = engine.start_session(user)
            run.add_metric("exam_id", body.exam_id)
            run.add_metric("course_id", engine.assessment.course_id)
            run.set_context(
                session_id=response["session_id"],
                question_id=response["question_id"],
            )
            with run.stage("examiner_media"):
                response = add_media(response, app.state.media, "prompt", engine.examiner)
                retain_question_video(response, engine)
                return response
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
    response_start: str = Form(...),
    response_end: str = Form(...),
    interaction_id: str = Form(...),
    user: dict = Depends(require_portal_student),
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
            engine = await run_in_threadpool(
                app.state.manager.engine_for_session, session_id, user["id"]
            )
            start, end = timestamp(response_start), timestamp(response_end)
            with engine.sessions._connection() as c:
                active = c.execute('SELECT InteractionID FROM INTERACTION WHERE SessionID=? AND Evaluation IS NULL',(session_id,)).fetchone()
                if not active or active[0] != interaction_id:
                    raise ValueError('This answer does not belong to the active interaction')
                full = c.execute('SELECT RecordingStatus FROM RECORDING WHERE RecordingID=?',(session_id,)).fetchone()
                status = c.execute('SELECT SessionStatus FROM "SESSION" WHERE SessionID=?',(session_id,)).fetchone()
                if not full or full[0] != 'recording' or status[0] != 'active':
                    raise ValueError('Full session recording must be active before answering')
            audio_format = content_type.split(';')[0].strip().lower()
            suffix = {'audio/webm':'.webm','audio/ogg':'.ogg','audio/wav':'.wav',
                      'audio/x-wav':'.wav','audio/mpeg':'.mp3','audio/mp4':'.m4a',
                      'audio/flac':'.flac'}.get(audio_format,'.audio')
            recording_path = RECORDINGS_DIR / f"{uuid.uuid4()}{suffix}"
            recording_path.write_bytes(payload)
            with run.stage("speech_to_text"):
                transcript = await run_in_threadpool(
                    transcribe_audio, app.state.whisper, recording_path
                )
            run.add_metric("transcript_words", len(transcript.split()))
            with run.stage("assessment_engine"):
                run.add_metric("exam_id", engine.exam_id)
                run.add_metric("course_id", engine.assessment.course_id)
                response = await run_in_threadpool(
                    engine.submit_response, session_id, transcript,
                    {"path": str(recording_path), "format": audio_format, "start_time":start,"end_time":end,"interaction_id":interaction_id},
                )
            run.set_context(question_id=response["question_id"])
            with run.stage("examiner_media"):
                response = await run_in_threadpool(
                    add_media, response, app.state.media, "next_prompt", engine.examiner
                )
                retain_question_video(response, engine)
            return response
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Assessment session not found"
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if engine is not None:
            await run_in_threadpool(engine.close)


def retain_question_video(response, engine):
    """Keep an audit copy separate from the regenerable media cache."""
    url = response.get('media_url')
    interaction_id = response.get('interaction_id')
    if not url or not interaction_id:
        return
    source = app.state.settings.media_dir / Path(url).name
    if source.suffix != '.mp4':
        return
    destination = RECORDINGS_DIR / response['session_id'] / (interaction_id + '.mp4')
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,destination)
    engine.sessions.question_media(response['session_id'], str(destination))


class RecordingEvent(BaseModel):
    event: str
    timestamp: str
    interaction_id: str | None = None
    chunk_count: int = 0


@app.post('/api/sessions/{session_id}/recording-events')
def recording_event(session_id: str, body: RecordingEvent, user: dict = Depends(require_portal_student)):
    try:
        app.state.manager.session_for_student(session_id,user['id'])
        sessions = app.state.manager.sessions
        store = FullRecordingStore(sessions.path, RECORDINGS_DIR)
        if body.event == 'recording_start':
            store.start(session_id,body.timestamp)
        elif body.event in ('question_start','question_end'):
            with sessions._connection() as c:
                active = c.execute('SELECT RecordingStatus FROM RECORDING WHERE RecordingID=?',(session_id,)).fetchone()
                if not active or active[0] != 'recording':
                    raise ValueError('Full session recording must be active before question playback')
            sessions.timing_event(session_id,body.interaction_id,body.event,timestamp(body.timestamp))
        elif body.event in ('recording_end','recording_interrupted'):
            store.finish(session_id,body.chunk_count,body.timestamp,body.event == 'recording_interrupted')
        else:
            raise ValueError('Unknown recording event')
        return {'ok':True}
    except PermissionError as exc:
        raise HTTPException(403,str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404,'Session not found') from exc
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@app.post('/api/sessions/{session_id}/recording-chunks/{index}')
async def recording_chunk(session_id: str, index: int, video: UploadFile = File(...), user: dict = Depends(require_portal_student)):
    try:
        await run_in_threadpool(app.state.manager.session_for_student,session_id,user['id'])
        payload = await video.read(32 * 1024 * 1024 + 1)
        if len(payload) > 32 * 1024 * 1024:
            raise HTTPException(413,'Recording segment is too large')
        await run_in_threadpool(FullRecordingStore(app.state.manager.sessions.path,RECORDINGS_DIR).chunk,session_id,index,payload)
        return {'ok':True}
    except PermissionError as exc:
        raise HTTPException(403,str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404,'Session not found') from exc
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


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
