"""
Faculty Exam Builder backend.

Serves the faculty page and turns uploaded course material into oral-exam
questions with Llama 3 running in Ollama.

Run:
    pip install -r requirements.txt
    ollama pull llama3
    cd faculty-portal
    python app.py
Then open http://127.0.0.1:8001/login

Port 8001 because speech-to-text/app.py (the student exam page) already uses 8000.

Faculty create courses, upload material to a course, and build exams from it:
    course -> documents -> generate (Llama 3 via Ollama) -> review -> publish

Pipeline position (matches the team's "Models used" table):
    Faculty uploads material  ->  THIS SERVER  ->  Llama 3 (Ollama)  ->  approved questions
    Published exams are saved as JSON in ./exams/ and served at GET /api/exams/{id}.
    The student side (avatar: XTTS v2 -> Wav2Lip, answers: Faster Whisper) reads from there.
"""

import io
import json
import random
import os
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

import auth
from auth import current_user, home_for, require_faculty, require_user
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from rag.analytics import AnalyticsStore, record_ollama_call
from rag.index import CourseIndex
from rag.profiles import profile_paths, save_profile
from rag.sessions import SessionStore

# ================= CONFIG (override with environment variables) =================
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")       # same tag as the team's table
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))              # Llama 3 8B max. Ollama's own default is smaller.
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))     # seconds per call; local CPU runs are slow
PORT = int(os.getenv("PORT", "8001"))   # 8000 is taken by speech-to-text/app.py
HOST = os.getenv("HOST", "127.0.0.1")                    # matches pipeline.py; set 0.0.0.0 to allow other machines (no login, see README)
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "").split(",") if o]  # empty = same-origin only (the page is served by this server)

CHUNK_CHARS = 1500          # ~375 tokens per chunk
CHUNKS_PER_QUESTION = 3     # ~1.1K tokens of material per prompt, well inside 8K
MAX_UPLOAD_MB = 25
ALLOWED_EXT = {".pdf", ".docx", ".pptx", ".txt", ".md"}

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "exam_builder.db")).resolve()
EXAMS_DIR = Path(os.getenv("FACULTY_EXAMS_DIR", BASE_DIR / "exams")).resolve()
COURSE_STORAGE_DIR = Path(
    os.getenv("FACULTY_COURSE_STORAGE", ROOT_DIR / "runtime" / "faculty-courses")
).resolve()
COURSE_INDEX_DIR = Path(
    os.getenv("FACULTY_INDEX_STORAGE", ROOT_DIR / "runtime" / "faculty-indexes")
).resolve()
ANALYTICS_DB_PATH = Path(
    os.getenv("ANALYTICS_DB_PATH", ROOT_DIR / "runtime" / "analytics.sqlite3")
).resolve()
SESSION_DB_PATH = Path(
    os.getenv("SESSION_DB_PATH", ROOT_DIR / "runtime" / "sessions.sqlite3")
).resolve()
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
ANALYTICS_BASE_WATTS = float(os.getenv("ANALYTICS_BASE_WATTS", "30"))
STATIC_PAGE = BASE_DIR / "index.html"   # same layout as speech-to-text/
LOGIN_PAGE = BASE_DIR / "login.html"
EXAMS_DIR.mkdir(parents=True, exist_ok=True)
COURSE_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
COURSE_INDEX_DIR.mkdir(parents=True, exist_ok=True)
ANALYTICS = AnalyticsStore(ANALYTICS_DB_PATH, ANALYTICS_BASE_WATTS)
TRANSCRIPTS = SessionStore(SESSION_DB_PATH)

# ================= DATABASE (SQLite, no setup needed) =================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _add_column(c, table: str, column: str, decl: str) -> None:
    """Tiny migration helper: add a column to an existing database if it's missing."""
    cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            term TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS materials (
            id TEXT PRIMARY KEY, filename TEXT, uploaded_at TEXT, characters INTEGER);
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, idx INTEGER, text TEXT,
            FOREIGN KEY (material_id) REFERENCES materials(id));
        CREATE TABLE IF NOT EXISTS exams (
            id TEXT PRIMARY KEY, course TEXT, title TEXT, settings TEXT, questions TEXT,
            status TEXT, created_at TEXT, published_at TEXT);
        """)
        # Columns added when courses were introduced (keeps older databases working).
        _add_column(c, "materials", "course_id", "TEXT")
        _add_column(c, "materials", "size", "INTEGER")
        _add_column(c, "materials", "relative_path", "TEXT")
        _add_column(c, "materials", "storage_path", "TEXT")
        _add_column(c, "exams", "course_id", "TEXT")
        _add_column(c, "exams", "professor_id", "INTEGER")
        _add_column(c, "exams", "media_version", "TEXT")
        c.execute("""CREATE TABLE IF NOT EXISTS professor_media (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            version TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_materials_course ON materials(course_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_exams_course ON exams(course_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_chunks_material ON chunks(material_id)")


init_db()


def course_materials_dir(course_id: str) -> Path:
    return COURSE_STORAGE_DIR / course_id / "materials"


def course_index_dir(course_id: str) -> Path:
    return COURSE_INDEX_DIR / course_id / "qdrant"


def mark_course_index_dirty(course_id: str) -> None:
    (course_index_dir(course_id).parent / "manifest.json").unlink(missing_ok=True)


def clean_relative_path(value: str, fallback: str) -> Path:
    """Return a safe relative upload path while preserving folder structure."""
    raw = (value or fallback).replace("\\", "/").strip("/")
    parts = [part for part in PurePosixPath(raw).parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(400, "Invalid upload path.")
    safe_parts = [re.sub(r"[^A-Za-z0-9._() -]", "_", part) for part in parts]
    return Path(*safe_parts)

# ================= TEXT EXTRACTION =================
def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md"):
        return data.decode("utf-8", errors="ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == ".docx":
        import docx
        d = docx.Document(io.BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        slides = []
        for n, slide in enumerate(prs.slides, 1):
            texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
                texts.append("Speaker notes: " + slide.notes_slide.notes_text_frame.text)
            if texts:
                slides.append(f"[Slide {n}]\n" + "\n".join(texts))
        return "\n\n".join(slides)
    raise ValueError(f"Unsupported file type: {ext}")


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on paragraph boundaries, packing paragraphs up to ~size characters."""
    text = re.sub(r"[ \t]+", " ", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        while len(p) > size:                     # very long paragraph: hard split
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(p[:size]); p = p[size:]
        if len(cur) + len(p) + 2 > size and cur:
            chunks.append(cur); cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if len(c) > 80]    # drop slivers like page numbers


# ================= RETRIEVAL =================
# Keyword overlap, not embeddings: zero extra models to download.
# Swap in Ollama embeddings (e.g. nomic-embed-text) later if quality isn't good enough.
STOP = set("the a an and or of to in on for with is are be by as at from that this it its into how what why when which".split())


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in STOP}


def pick_chunks(material_ids: list[str], focus_topics: list[str], n_questions: int) -> list[list[dict]]:
    """Return one list of chunks per question, spreading questions across the material."""
    with db() as c:
        marks = ",".join("?" * len(material_ids))
        rows = c.execute(
            f"""SELECT ch.text, ch.idx, m.filename FROM chunks ch JOIN materials m ON m.id = ch.material_id
                WHERE ch.material_id IN ({marks}) ORDER BY m.uploaded_at, ch.idx""", material_ids).fetchall()
    if not rows:
        raise HTTPException(400, "No readable text in the uploaded material. Scanned PDFs need OCR first.")
    chunks = [dict(r) for r in rows]

    if focus_topics:
        q = words(" ".join(focus_topics))
        scored = sorted(chunks, key=lambda ch: len(q & words(ch["text"])), reverse=True)
        relevant = [ch for ch in scored if q & words(ch["text"])]
        pool = relevant if len(relevant) >= n_questions else scored
    else:
        pool = chunks

    # Spread question anchors evenly through the pool, then add neighbours for context.
    groups = []
    step = max(1, len(pool) // n_questions)
    for i in range(n_questions):
        anchor = (i * step) % len(pool)
        group = [pool[(anchor + k) % len(pool)] for k in range(min(CHUNKS_PER_QUESTION, len(pool)))]
        groups.append(group)
    return groups


# ================= LLAMA 3 VIA OLLAMA =================
STYLE_TEXT = {
    "conceptual": "ask the student to explain a concept in their own words",
    "application": "give a short scenario and ask the student to apply a concept to it",
    "compare": "ask the student to compare and contrast two related ideas",
    "justify": "ask the student to make and defend a decision",
}
LEVEL_TEXT = {
    "intro": "introductory: recall and define",
    "intermediate": "intermediate: explain and apply",
    "advanced": "advanced: analyze and evaluate",
}

SYSTEM_PROMPT = (
    "You write questions for spoken (oral) university exams. The student hears the question read aloud "
    "by an avatar and answers out loud, so questions must be one or two plain sentences, with no lists, "
    "code, tables, formulas, or references to figures. Use ONLY the course material provided. "
    "Respond with JSON only."
)


def build_prompt(material: list[dict], s: "GenerateRequest", style: str, avoid: list[str]) -> str:
    excerpt = "\n\n---\n\n".join(f"(from {m['filename']})\n{m['text']}" for m in material)
    follow = ('"follow_up": "one short probing question to ask after the student answers",'
              if s.include_follow_ups else "")
    avoid_txt = ("\nDo NOT repeat or closely paraphrase these existing questions:\n- " + "\n- ".join(avoid)) if avoid else ""
    return f"""COURSE: {s.course}
DIFFICULTY: {LEVEL_TEXT.get(s.difficulty, s.difficulty)}
QUESTION STYLE: {STYLE_TEXT.get(style, style)}
{"FOCUS TOPICS: " + ", ".join(s.focus_topics) if s.focus_topics else ""}

COURSE MATERIAL:
{excerpt}
{avoid_txt}

Write exactly ONE oral exam question based on the material above.
Return JSON with exactly these keys:
{{
  "question": "the question, spoken-friendly",
  "key_points": ["3 to 5 short points a strong answer must cover, taken from the material"],
  {follow}
  "source_quote": "a short sentence copied from the material that the question is based on"
}}"""


async def ask_llama(prompt: str) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "format": "json",                         # forces valid JSON from Llama 3
        "stream": False,
        "options": {"num_ctx": NUM_CTX, "temperature": TEMPERATURE},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
    except httpx.ConnectError:
        raise HTTPException(503, f"Can't reach Ollama at {OLLAMA_URL}. Start it with 'ollama serve'.")
    except httpx.TimeoutException:
        raise HTTPException(504, f"Llama 3 took longer than {LLM_TIMEOUT:.0f}s. Try fewer questions or raise LLM_TIMEOUT.")
    if r.status_code == 404:
        raise HTTPException(503, f"Model '{OLLAMA_MODEL}' isn't pulled. Run: ollama pull {OLLAMA_MODEL}")
    r.raise_for_status()
    body = r.json()
    record_ollama_call(body, operation="question_generation", model=OLLAMA_MODEL, item_count=1)
    content = body["message"]["content"]
    return json.loads(content)


def clean_question(raw: dict, material: list[dict], include_follow_up: bool) -> Optional[dict]:
    """Validate Llama's output. Returns None if it's unusable so the caller can retry."""
    q = str(raw.get("question", "")).strip()
    kp = raw.get("key_points", [])
    if isinstance(kp, str):
        kp = [x.strip(" -•") for x in kp.split("\n") if x.strip()]
    kp = [str(x).strip() for x in kp if str(x).strip()]
    if len(q) < 15 or not kp:
        return None
    # Use the chunk Llama quoted from as the source; fall back to the first chunk.
    quote = str(raw.get("source_quote", "")).strip()
    src = next((m for m in material if quote and quote[:40].lower() in m["text"].lower()), material[0])
    out = {
        "id": "q_" + uuid.uuid4().hex[:8],
        "question": q,
        "key_points": kp[:5],
        "source_file": src["filename"],
        "source_excerpt": src["text"][:700] + ("…" if len(src["text"]) > 700 else ""),
    }
    if include_follow_up:
        out["follow_up"] = str(raw.get("follow_up", "")).strip()
    return out


async def generate_one(material, s, style, avoid, attempts=3) -> dict:
    for _ in range(attempts):
        try:
            raw = await ask_llama(build_prompt(material, s, style, avoid))
        except json.JSONDecodeError:
            continue
        q = clean_question(raw, material, s.include_follow_ups)
        if q:
            return q
    raise HTTPException(502, "Llama 3 returned unusable output three times in a row. Try again or adjust the settings.")


# ================= API MODELS =================
class CourseIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    term: str = Field("", max_length=40)


class GenerateRequest(BaseModel):
    course_id: str
    course: str = ""                 # filled in by the server from the course record
    title: str = Field("", max_length=200)
    seconds_per_question: int = Field(180, ge=30, le=1800)
    material_ids: list[str] = []     # empty = every document in the course
    num_questions: int = Field(5, ge=1, le=20)
    difficulty: str = "intermediate"
    styles: list[str] = ["conceptual"]
    focus_topics: list[str] = []
    include_follow_ups: bool = True


class RegenerateRequest(GenerateRequest):
    question_id: str


class PublishRequest(GenerateRequest):
    questions: list[dict]


# ================= OWNERSHIP HELPERS =================
# Faculty only ever see their own courses. Anything else is a 404, so IDs of
# other people's courses and exams can't be probed.
def get_course(course_id: str, user: dict) -> dict:
    with db() as c:
        row = c.execute("SELECT * FROM courses WHERE id=? AND owner_id=?", (course_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Course not found.")
    return dict(row)


def get_exam_row(exam_id: str, user: dict) -> dict:
    check_exam_id(exam_id)
    with db() as c:
        row = c.execute("""SELECT e.* FROM exams e JOIN courses co ON co.id = e.course_id
                           WHERE e.id=? AND co.owner_id=?""", (exam_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Exam not found.")
    return dict(row)


def resolve_materials(course: dict, material_ids: list[str]) -> list[str]:
    """Every requested document must belong to this course. Empty list = all of them."""
    with db() as c:
        owned = [r["id"] for r in c.execute("SELECT id FROM materials WHERE course_id=? ORDER BY uploaded_at",
                                            (course["id"],))]
    if not owned:
        raise HTTPException(400, f"{course['code']} has no documents yet. Upload course material first.")
    if not material_ids:
        return owned
    bad = set(material_ids) - set(owned)
    if bad:
        raise HTTPException(400, "Some selected documents don't belong to this course.")
    return material_ids


def check_exam_id(exam_id: str) -> None:
    if not re.fullmatch(r"exam_[0-9a-f]{10}", exam_id):
        raise HTTPException(404, "Exam not found.")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ================= APP + PAGES =================
app = FastAPI(title="Faculty Exam Builder")
if CORS_ORIGINS:   # only needed if the page is hosted somewhere other than this server
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)


@app.get("/login")
def login_page():
    # Keep the role chooser reachable so a shared browser can switch accounts.
    return FileResponse(LOGIN_PAGE, headers={"Cache-Control": "no-store"})


@app.get("/")
def index(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["role"] != "faculty":              # students never see the exam builder
        return RedirectResponse(home_for(user, request), status_code=303)
    return FileResponse(STATIC_PAGE, headers={"Cache-Control": "no-store"})


@app.get("/api/health", dependencies=[Depends(require_faculty)])
async def health():
    question_model_ready = False
    embedding_model_ready = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            tags = (await client.get(f"{OLLAMA_URL}/api/tags")).json()
        names = {m["name"].split(":")[0] for m in tags.get("models", [])}
        question_model_ready = OLLAMA_MODEL.split(":")[0] in names
        embedding_model_ready = EMBED_MODEL.split(":")[0] in names
    except Exception:
        pass
    return {"server": True, "ollama": question_model_ready and embedding_model_ready,
            "question_model_ready": question_model_ready,
            "embedding_model_ready": embedding_model_ready,
            "model": OLLAMA_MODEL, "ollama_url": OLLAMA_URL, "embedding_model": EMBED_MODEL}


@app.get("/api/analytics/summary")
def analytics_summary(user: dict = Depends(require_faculty)):
    return ANALYTICS.summary()


@app.get("/api/analytics/runs")
def analytics_runs(limit: int = 50, user: dict = Depends(require_faculty)):
    return {"runs": ANALYTICS.recent_runs(limit)}


@app.get("/api/transcripts")
def assessment_transcripts(
    limit: int = 50, user: dict = Depends(require_faculty)
):
    """Return transcripts only for exams owned by the signed-in professor."""
    with db() as connection:
        rows = connection.execute(
            """SELECT e.id AS exam_id, e.title, co.code AS course
               FROM exams e JOIN courses co ON co.id=e.course_id
               WHERE co.owner_id=?""",
            (user["id"],),
        ).fetchall()
    exams = {
        str(row["exam_id"]): {
            "exam_title": row["title"] or "Untitled exam",
            "course": row["course"],
        }
        for row in rows
    }
    sessions = TRANSCRIPTS.list_for_exams(list(exams), limit)
    for session in sessions:
        session.update(exams.get(str(session["exam_id"]), {}))
    return {"sessions": sessions}


# ================= COURSES =================
@app.get("/api/courses")
def list_courses(user: dict = Depends(require_faculty)):
    with db() as c:
        rows = c.execute("""
            SELECT co.id, co.code, co.name, co.term, co.created_at,
              (SELECT COUNT(*) FROM materials m WHERE m.course_id = co.id) AS documents,
              (SELECT COUNT(*) FROM exams e WHERE e.course_id = co.id) AS exams,
              (SELECT COUNT(*) FROM exams e WHERE e.course_id = co.id AND e.status='published') AS published
            FROM courses co WHERE co.owner_id=? ORDER BY co.code""", (user["id"],)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/courses")
def create_course(body: CourseIn, user: dict = Depends(require_faculty)):
    cid = "crs_" + uuid.uuid4().hex[:10]
    with db() as c:
        c.execute("INSERT INTO courses VALUES (?,?,?,?,?,?)",
                  (cid, user["id"], body.code.strip().upper(), body.name.strip(), body.term.strip(), now()))
    return get_course(cid, user)


@app.put("/api/courses/{course_id}")
def update_course(course_id: str, body: CourseIn, user: dict = Depends(require_faculty)):
    get_course(course_id, user)
    with db() as c:
        c.execute("UPDATE courses SET code=?, name=?, term=? WHERE id=?",
                  (body.code.strip().upper(), body.name.strip(), body.term.strip(), course_id))
    return get_course(course_id, user)


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: str, user: dict = Depends(require_faculty)):
    """Deletes the course, its documents, and its exams (including published ones)."""
    get_course(course_id, user)
    with db() as c:
        exam_ids = [r["id"] for r in c.execute("SELECT id FROM exams WHERE course_id=?", (course_id,))]
        c.execute("DELETE FROM chunks WHERE material_id IN (SELECT id FROM materials WHERE course_id=?)", (course_id,))
        c.execute("DELETE FROM materials WHERE course_id=?", (course_id,))
        c.execute("DELETE FROM exams WHERE course_id=?", (course_id,))
        c.execute("DELETE FROM courses WHERE id=?", (course_id,))
    for eid in exam_ids:
        (EXAMS_DIR / f"{eid}.json").unlink(missing_ok=True)
    shutil.rmtree(COURSE_STORAGE_DIR / course_id, ignore_errors=True)
    shutil.rmtree(COURSE_INDEX_DIR / course_id, ignore_errors=True)
    return {"ok": True, "deleted_exams": len(exam_ids)}


# ================= COURSE DOCUMENTS =================
@app.get("/api/courses/{course_id}/materials")
def list_materials(course_id: str, user: dict = Depends(require_faculty)):
    get_course(course_id, user)
    with db() as c:
        rows = c.execute("""SELECT m.id AS material_id, m.filename, m.relative_path, m.size, m.characters, m.uploaded_at,
                                   (SELECT COUNT(*) FROM chunks ch WHERE ch.material_id = m.id) AS chunks
                            FROM materials m WHERE m.course_id=? ORDER BY m.uploaded_at""", (course_id,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/courses/{course_id}/materials")
async def upload_material(
    course_id: str,
    file: UploadFile = File(...),
    relative_path: str = Form(""),
    user: dict = Depends(require_faculty),
):
    get_course(course_id, user)
    upload_path = clean_relative_path(relative_path, file.filename or "upload")
    ext = upload_path.suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type {ext}. Use {', '.join(sorted(ALLOWED_EXT))}.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"File is over {MAX_UPLOAD_MB} MB.")
    try:
        text = extract_text(file.filename, data)
    except Exception as e:
        raise HTTPException(400, f"Couldn't read {file.filename}: {e}")
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(400, "No readable text found. If it's a scanned PDF, run OCR on it first.")
    mid = "mat_" + uuid.uuid4().hex[:10]
    uploaded = now()
    storage_path = (course_materials_dir(course_id) / upload_path).resolve()
    materials_root = course_materials_dir(course_id).resolve()
    if materials_root not in storage_path.parents:
        raise HTTPException(400, "Invalid upload path.")
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(data)
    mark_course_index_dirty(course_id)
    with db() as c:
        previous = c.execute(
            "SELECT id, storage_path FROM materials WHERE course_id=? AND relative_path=?",
            (course_id, upload_path.as_posix()),
        ).fetchone()
        if previous:
            c.execute("DELETE FROM chunks WHERE material_id=?", (previous["id"],))
            c.execute("DELETE FROM materials WHERE id=?", (previous["id"],))
        c.execute("""INSERT INTO materials
                     (id, filename, uploaded_at, characters, course_id, size, relative_path, storage_path)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (mid, upload_path.name, uploaded, len(text), course_id, len(data),
                   upload_path.as_posix(), str(storage_path)))
        c.executemany("INSERT INTO chunks (material_id, idx, text) VALUES (?,?,?)",
                      [(mid, i, ch) for i, ch in enumerate(chunks)])
    return {"material_id": mid, "filename": upload_path.name, "relative_path": upload_path.as_posix(),
            "size": len(data), "chunks": len(chunks), "characters": len(text), "uploaded_at": uploaded}


@app.delete("/api/courses/{course_id}/materials/{material_id}")
def delete_material(course_id: str, material_id: str, user: dict = Depends(require_faculty)):
    get_course(course_id, user)
    with db() as c:
        row = c.execute(
            "SELECT storage_path FROM materials WHERE id=? AND course_id=?",
            (material_id, course_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        cur = c.execute("DELETE FROM materials WHERE id=? AND course_id=?", (material_id, course_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Document not found.")
        c.execute("DELETE FROM chunks WHERE material_id=?", (material_id,))
        remaining = c.execute(
            "SELECT COUNT(*) FROM materials WHERE course_id=?", (course_id,)
        ).fetchone()[0]
    if row["storage_path"]:
        Path(row["storage_path"]).unlink(missing_ok=True)
    mark_course_index_dirty(course_id)
    if not remaining:
        shutil.rmtree(COURSE_INDEX_DIR / course_id, ignore_errors=True)
    return {"ok": True}


@app.get("/api/courses/{course_id}/index")
def course_index_status(course_id: str, user: dict = Depends(require_faculty)):
    get_course(course_id, user)
    manifest_path = course_index_dir(course_id).parent / "manifest.json"
    if not manifest_path.is_file():
        return {"ready": False, "course_id": course_id, "document_count": 0, "chunk_count": 0,
                "indexed_at": None, "embedding_model": EMBED_MODEL}
    status = json.loads(manifest_path.read_text(encoding="utf-8"))
    status["ready"] = (
        status.get("course_id") == course_id
        and status.get("embedding_model") == EMBED_MODEL
    )
    return status


@app.post("/api/courses/{course_id}/index")
async def rebuild_course_index(course_id: str, user: dict = Depends(require_faculty)):
    course = get_course(course_id, user)
    material_dir = course_materials_dir(course_id)
    with ANALYTICS.run("course_index") as run:
        run.add_metric("course_id", course_id)
        run.add_metric("course_code", course["code"])
        with run.stage("course_extraction_and_embedding"):
            index = CourseIndex(course_index_dir(course_id), EMBED_MODEL)
            try:
                status = await run_in_threadpool(index.rebuild, material_dir, course_id)
            finally:
                index.close()
        run.add_metric("document_count", status["document_count"])
        run.add_metric("chunk_count", status["chunk_count"])
    return {**status, "ready": True}


# ================= EXAMS (faculty) =================
@app.get("/api/courses/{course_id}/exams")
def list_course_exams(course_id: str, user: dict = Depends(require_faculty)):
    get_course(course_id, user)
    with db() as c:
        rows = c.execute("""SELECT id AS exam_id, title, status, created_at, published_at, settings, questions
                            FROM exams WHERE course_id=? ORDER BY created_at DESC""", (course_id,)).fetchall()
    out = []
    for r in rows:
        settings = json.loads(r["settings"] or "{}")
        out.append({"exam_id": r["exam_id"], "title": r["title"] or "Untitled exam", "status": r["status"],
                    "created_at": r["created_at"], "published_at": r["published_at"],
                    "question_count": len(json.loads(r["questions"] or "[]")),
                    "seconds_per_question": settings.get("seconds_per_question", 180)})
    return out


@app.get("/api/exams/{exam_id}/edit")
def open_exam_for_editing(exam_id: str, user: dict = Depends(require_faculty)):
    row = get_exam_row(exam_id, user)
    return {"exam_id": row["id"], "course_id": row["course_id"], "status": row["status"],
            "settings": json.loads(row["settings"] or "{}"), "questions": json.loads(row["questions"] or "[]")}


@app.post("/api/exams/generate")
async def generate(s: GenerateRequest, user: dict = Depends(require_faculty)):
    course = get_course(s.course_id, user)
    s.course = course["code"]
    s.material_ids = resolve_materials(course, s.material_ids)
    styles = s.styles or ["conceptual"]
    groups = pick_chunks(s.material_ids, s.focus_topics, s.num_questions)
    questions = []
    with ANALYTICS.run("question_generation") as run:
        run.add_metric("course_id", course["id"])
        run.add_metric("requested_questions", s.num_questions)
        run.add_metric("source_documents", len(s.material_ids))
        for i, material in enumerate(groups):          # one Llama call per question = better grounding
            with run.stage("question_generation"):
                q = await generate_one(material, s, styles[i % len(styles)], [x["question"] for x in questions])
            questions.append(q)
        run.add_metric("generated_questions", len(questions))
    exam_id = "exam_" + uuid.uuid4().hex[:10]
    with db() as c:
        c.execute("INSERT INTO exams (id, course, title, settings, questions, status, created_at, published_at, course_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (exam_id, course["code"], s.title, s.model_dump_json(), json.dumps(questions),
                   "draft", now(), None, course["id"]))
    return {"exam_id": exam_id, "questions": questions}


@app.post("/api/exams/{exam_id}/regenerate")
async def regenerate(exam_id: str, s: RegenerateRequest, user: dict = Depends(require_faculty)):
    row = get_exam_row(exam_id, user)
    course = get_course(row["course_id"], user)
    s.course = course["code"]
    s.material_ids = resolve_materials(course, s.material_ids)
    existing = json.loads(row["questions"])
    material = random.choice(pick_chunks(s.material_ids, s.focus_topics, max(3, s.num_questions)))
    style = random.choice(s.styles or ["conceptual"])
    with ANALYTICS.run("question_regeneration", question_id=s.question_id) as run:
        run.add_metric("course_id", course["id"])
        with run.stage("question_generation"):
            q = await generate_one(material, s, style, [x["question"] for x in existing])
    existing = [q if x["id"] == s.question_id else x for x in existing]
    with db() as c:
        c.execute("UPDATE exams SET questions=? WHERE id=?", (json.dumps(existing), exam_id))
    return q


@app.put("/api/exams/{exam_id}")
def save_draft(exam_id: str, s: PublishRequest, user: dict = Depends(require_faculty)):
    """Save edits without publishing. Students keep seeing the last published version."""
    get_exam_row(exam_id, user)
    with db() as c:
        c.execute("UPDATE exams SET title=?, settings=?, questions=? WHERE id=?",
                  (s.title, GenerateRequest(**s.model_dump(exclude={"questions"})).model_dump_json(),
                   json.dumps(s.questions), exam_id))
    return {"ok": True}


def professor_profile(user_id: int) -> dict | None:
    with db() as c:
        row = c.execute("SELECT version, updated_at FROM professor_media WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


@app.get("/api/profile/media")
def get_profile_media(user: dict = Depends(require_faculty)):
    profile = professor_profile(user["id"])
    return {"configured": bool(profile), **(profile or {})}


@app.post("/api/profile/media")
async def upload_profile_media(
    photo: UploadFile = File(...), voice: UploadFile = File(...),
    user: dict = Depends(require_faculty),
):
    if Path(photo.filename or "").suffix.lower() != ".png" or Path(voice.filename or "").suffix.lower() != ".wav":
        raise HTTPException(415, "Upload a PNG photo and a WAV voice recording")
    photo_bytes = await photo.read(10 * 1024 * 1024 + 1)
    voice_bytes = await voice.read(6 * 1024 * 1024 + 1)
    if len(photo_bytes) > 10 * 1024 * 1024 or len(voice_bytes) > 6 * 1024 * 1024:
        raise HTTPException(413, "Photo limit is 10 MB; voice limit is 6 MB")
    try:
        version = await run_in_threadpool(save_profile, user["id"], photo_bytes, voice_bytes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with db() as c:
        c.execute("""INSERT INTO professor_media (user_id, version, updated_at) VALUES (?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET version=excluded.version, updated_at=excluded.updated_at""",
            (user["id"], version, now()))
    return {"ok": True, "version": version}


@app.get("/api/profile/media/{kind}")
def preview_profile_media(kind: str, user: dict = Depends(require_faculty)):
    if kind not in {"photo", "voice"}:
        raise HTTPException(404, "Media not found")
    profile = professor_profile(user["id"])
    if not profile:
        raise HTTPException(404, "Upload your professor avatar first")
    paths = profile_paths(user["id"], profile["version"])
    path = paths[0 if kind == "photo" else 1]
    if not path.is_file():
        raise HTTPException(404, "Professor media file is missing; upload it again")
    return FileResponse(path, media_type="image/png" if kind == "photo" else "audio/wav",
                        headers={"Cache-Control": "private, no-store"})


@app.post("/api/exams/{exam_id}/publish")
def publish(exam_id: str, s: PublishRequest, user: dict = Depends(require_faculty)):
    row = get_exam_row(exam_id, user)
    course = get_course(row["course_id"], user)
    if not s.questions:
        raise HTTPException(400, "No questions to publish.")
    manifest_path = course_index_dir(course["id"]).parent / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(409, "Index this course's uploaded materials before publishing the exam.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("course_id") != course["id"] or manifest.get("embedding_model") != EMBED_MODEL:
        raise HTTPException(409, "The course index is out of date. Rebuild it before publishing.")
    published = now()
    profile = professor_profile(user["id"])
    if profile and not all(p.is_file() for p in profile_paths(user["id"], profile["version"])):
        raise HTTPException(409, "Your professor media files are missing. Upload them again before publishing.")
    exam = {
        "exam_id": exam_id,
        "course_id": course["id"],
        "course": course["code"],
        "course_name": course["name"],
        "term": course["term"],
        "title": s.title,
        "seconds_per_question": s.seconds_per_question,
        "published_at": published,
        "professor_id": user["id"],
        "examiner": {"professor_id": user["id"], "media_version": profile["version"]} if profile else None,
        "questions": [
            {"id": q.get("id"), "question": q.get("question", ""), "key_points": q.get("key_points", []),
             "follow_up": q.get("follow_up"), "source_file": q.get("source_file")}
            for q in s.questions
        ],
    }
    path = EXAMS_DIR / f"{exam_id}.json"
    path.write_text(json.dumps(exam, indent=2))
    settings = GenerateRequest(**s.model_dump(exclude={"questions"}))
    settings.course = course["code"]
    with db() as c:
        c.execute("UPDATE exams SET title=?, settings=?, questions=?, status='published', published_at=?, professor_id=?, media_version=? WHERE id=?",
                  (s.title, settings.model_dump_json(), json.dumps(s.questions), published,
                   user["id"], profile["version"] if profile else None, exam_id))
    display_path = path.relative_to(BASE_DIR) if path.is_relative_to(BASE_DIR) else path
    return {"ok": True, "exam_id": exam_id, "path": str(display_path)}


# ================= EXAMS (student side reads) =================
# Any signed-in user can read published exams. Students get the questions only:
# key_points is the answer key and must never reach a student's browser.
# Other pipeline stages can also read faculty-portal/exams/<id>.json from disk.
STUDENT_FIELDS = ("id", "question", "follow_up")


@app.get("/api/exams", dependencies=[Depends(require_user)])
def list_exams():
    with db() as c:
        rows = c.execute("""SELECT e.id, e.title, e.published_at, co.code AS course, co.name AS course_name, co.term
                            FROM exams e JOIN courses co ON co.id = e.course_id
                            WHERE e.status='published' ORDER BY e.published_at DESC""").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/exams/{exam_id}")
def get_exam(exam_id: str, user: dict = Depends(require_user)):
    check_exam_id(exam_id)
    path = EXAMS_DIR / f"{exam_id}.json"
    if not path.exists():
        raise HTTPException(404, "Exam not found or not published.")
    exam = json.loads(path.read_text())
    if user["role"] != "faculty":
        exam["questions"] = [{k: q.get(k) for k in STUDENT_FIELDS} for q in exam["questions"]]
    return exam


if __name__ == "__main__":
    import uvicorn
    print(f"Faculty Exam Builder → http://{HOST}:{PORT}/login   (Ollama: {OLLAMA_URL}, model: {OLLAMA_MODEL})")
    if auth.count_faculty() == 0:
        print("\n  !! No faculty accounts yet. Create one before signing in:")
        print("       python manage_users.py add <username> --role faculty --name \"Dr. Smith\"\n")
    uvicorn.run(app, host=HOST, port=PORT)
