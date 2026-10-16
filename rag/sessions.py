import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS assessment_sessions (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL,
                    exam_id TEXT,
                    question_index INTEGER NOT NULL DEFAULT 0,
                    follow_up_count INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assessment_turns (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    turn_number INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    retrieved_json TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES assessment_sessions(id)
                );
            """)
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(assessment_sessions)")
            }
            if "exam_id" not in columns:
                connection.execute("ALTER TABLE assessment_sessions ADD COLUMN exam_id TEXT")

    def create(self, course_id: str, exam_id: str | None = None) -> dict:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO assessment_sessions "
                "(id, course_id, exam_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, course_id, exam_id, now, now),
            )
        return self.get(session_id)

    def get(self, session_id: str) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM assessment_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return dict(row)

    def transcripts_for_question(self, session_id: str, question_id: str) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT transcript FROM assessment_turns "
                "WHERE session_id = ? AND question_id = ? ORDER BY turn_number",
                (session_id, question_id),
            ).fetchall()
        return [str(row["transcript"]) for row in rows]

    def record_turn_and_update(
        self,
        session_id: str,
        question_id: str,
        prompt: str,
        transcript: str,
        evaluation: dict,
        retrieved: list[dict],
        action: str,
        question_index: int,
        follow_up_count: int,
        completed: bool,
    ) -> str:
        """Save the audit turn and session progress in one transaction."""
        turn_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM assessment_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            connection.execute(
                "INSERT INTO assessment_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    turn_id,
                    session_id,
                    question_id,
                    int(row["count"]) + 1,
                    prompt,
                    transcript,
                    json.dumps(evaluation),
                    json.dumps(retrieved),
                    action,
                    now,
                ),
            )
            connection.execute(
                "UPDATE assessment_sessions SET question_index = ?, "
                "follow_up_count = ?, completed = ?, updated_at = ? WHERE id = ?",
                (
                    question_index,
                    follow_up_count,
                    int(completed),
                    now,
                    session_id,
                ),
            )
        return turn_id
