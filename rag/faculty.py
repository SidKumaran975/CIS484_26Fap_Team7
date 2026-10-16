"""Bridge between the faculty portal and the student assessment runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

from fastapi import HTTPException, Request

from .config import ROOT_DIR, Settings
from .engine import AssessmentEngine
from .schemas import AssessmentDefinition, Question, RubricCriterion
from .sessions import SessionStore

SESSION_COOKIE = "examportal_session"
FACULTY_DIR = ROOT_DIR / "faculty-portal"
FACULTY_DB_PATH = Path(
    os.environ.get("FACULTY_DB_PATH", FACULTY_DIR / "exam_builder.db")
).resolve()
FACULTY_EXAMS_DIR = Path(
    os.environ.get("FACULTY_EXAMS_DIR", FACULTY_DIR / "exams")
).resolve()
FACULTY_COURSE_STORAGE = Path(
    os.environ.get("FACULTY_COURSE_STORAGE", ROOT_DIR / "runtime" / "faculty-courses")
).resolve()
FACULTY_INDEX_STORAGE = Path(
    os.environ.get("FACULTY_INDEX_STORAGE", ROOT_DIR / "runtime" / "faculty-indexes")
).resolve()


def _connect() -> sqlite3.Connection:
    if not FACULTY_DB_PATH.is_file():
        raise HTTPException(503, "The faculty portal has not been initialized yet.")
    connection = sqlite3.connect(FACULTY_DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def current_portal_user(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not FACULTY_DB_PATH.is_file():
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _connect() as connection:
        row = connection.execute(
            """SELECT u.id, u.username, u.display_name, u.role, s.expires_at
               FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=?""",
            (token_hash,),
        ).fetchone()
    if not row or float(row["expires_at"]) < time.time():
        return None
    return {key: row[key] for key in ("id", "username", "display_name", "role")}


def require_portal_user(request: Request) -> dict:
    user = current_portal_user(request)
    if not user:
        raise HTTPException(401, "Sign in through the faculty portal first.")
    return user


def require_portal_student(request: Request) -> dict:
    """Require a student account for the assessment-delivery service."""
    user = require_portal_user(request)
    if user["role"] != "student":
        raise HTTPException(403, "A student account is required to take an assessment.")
    return user


def list_published_exams() -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT e.id AS exam_id, e.title, e.published_at,
                      co.code AS course, co.name AS course_name, co.term
               FROM exams e JOIN courses co ON co.id=e.course_id
               WHERE e.status='published' ORDER BY e.published_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]


def load_published_exam(exam_id: str) -> tuple[dict, Path]:
    if not re.fullmatch(r"exam_[0-9a-f]{10}", exam_id):
        raise KeyError(exam_id)
    path = FACULTY_EXAMS_DIR / f"{exam_id}.json"
    if not path.is_file():
        raise KeyError(exam_id)
    return json.loads(path.read_text(encoding="utf-8")), path


def assessment_from_exam(exam: dict) -> AssessmentDefinition:
    objectives: dict[str, str] = {}
    questions: list[Question] = []
    for question_number, raw in enumerate(exam.get("questions", []), start=1):
        question_id = str(raw.get("id") or f"Q{question_number:03d}")
        key_points = [str(point).strip() for point in raw.get("key_points", []) if str(point).strip()]
        if not key_points:
            key_points = ["The response directly and accurately addresses the question."]
        objective_ids: list[str] = []
        rubric: list[RubricCriterion] = []
        for point_number, point in enumerate(key_points, start=1):
            objective_id = f"{question_id}_O{point_number}"
            criterion_id = f"{question_id}_R{point_number}"
            objectives[objective_id] = point
            objective_ids.append(objective_id)
            rubric.append(RubricCriterion(id=criterion_id, description=point, required=True))
        questions.append(
            Question(
                id=question_id,
                prompt=str(raw.get("question", "")).strip(),
                objectives=objective_ids,
                rubric=rubric,
            )
        )
    if not questions:
        raise ValueError("The published exam contains no questions.")
    return AssessmentDefinition(
        course_id=str(exam["course_id"]),
        title=str(exam.get("title") or exam.get("course") or "Oral assessment"),
        objectives=objectives,
        questions=questions,
    )


class FacultyAssessmentManager:
    """Loads published exams and routes sessions to their course-specific index."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.sessions = SessionStore(settings.session_db_path)

    def close(self) -> None:
        return

    def engine_for_exam(self, exam_id: str) -> AssessmentEngine:
        exam, _ = load_published_exam(exam_id)
        course_id = str(exam["course_id"])
        course_settings = replace(
            self.settings,
            course_content_dir=FACULTY_COURSE_STORAGE / course_id / "materials",
            vector_db_path=FACULTY_INDEX_STORAGE / course_id / "qdrant",
        )
        engine = AssessmentEngine(
            course_settings,
            assessment=assessment_from_exam(exam),
            exam_id=exam_id,
        )
        return engine

    def engine_for_session(self, session_id: str) -> AssessmentEngine:
        session = self.sessions.get(session_id)
        exam_id = session.get("exam_id")
        if not exam_id:
            raise ValueError("This session is not linked to a published faculty exam.")
        return self.engine_for_exam(str(exam_id))
