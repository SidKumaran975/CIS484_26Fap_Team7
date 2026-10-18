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
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
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
                    student_id INTEGER,
                    student_username TEXT,
                    student_name TEXT,
                    question_index INTEGER NOT NULL DEFAULT 0,
                    follow_up_count INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    current_prompt TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
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
                    next_prompt TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES assessment_sessions(id)
                );
            """)
            session_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(assessment_sessions)")
            }
            session_migrations = {
                "exam_id": "TEXT",
                "student_id": "INTEGER",
                "student_username": "TEXT",
                "student_name": "TEXT",
                "current_prompt": "TEXT NOT NULL DEFAULT ''",
                "completed_at": "TEXT",
            }
            for column, declaration in session_migrations.items():
                if column not in session_columns:
                    connection.execute(
                        f"ALTER TABLE assessment_sessions ADD COLUMN {column} {declaration}"
                    )
            turn_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(assessment_turns)")
            }
            if "next_prompt" not in turn_columns:
                connection.execute(
                    "ALTER TABLE assessment_turns "
                    "ADD COLUMN next_prompt TEXT NOT NULL DEFAULT ''"
                )
            connection.executescript("""
                CREATE INDEX IF NOT EXISTS assessment_sessions_exam_created
                    ON assessment_sessions(exam_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS assessment_turns_session_number
                    ON assessment_turns(session_id, turn_number);
            """)

    def create(
        self,
        course_id: str,
        exam_id: str | None = None,
        *,
        student_id: int | None = None,
        student_username: str | None = None,
        student_name: str | None = None,
        initial_prompt: str = "",
    ) -> dict:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO assessment_sessions "
                "(id, course_id, exam_id, student_id, student_username, "
                "student_name, current_prompt, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    course_id,
                    exam_id,
                    student_id,
                    student_username,
                    student_name,
                    initial_prompt,
                    now,
                    now,
                ),
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
        next_prompt: str = "",
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
                "INSERT INTO assessment_turns "
                "(id, session_id, question_id, turn_number, prompt, transcript, "
                "evaluation_json, retrieved_json, action, next_prompt, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    next_prompt,
                    now,
                ),
            )
            connection.execute(
                "UPDATE assessment_sessions SET question_index = ?, "
                "follow_up_count = ?, completed = ?, current_prompt = ?, "
                "updated_at = ?, completed_at = CASE WHEN ? THEN ? ELSE completed_at END "
                "WHERE id = ?",
                (
                    question_index,
                    follow_up_count,
                    int(completed),
                    next_prompt,
                    now,
                    int(completed),
                    now,
                    session_id,
                ),
            )
        return turn_id

    def list_for_exams(self, exam_ids: list[str], limit: int = 50) -> list[dict]:
        """Return recent transcripts for the requested exams.

        Callers are responsible for supplying only exam IDs the current faculty
        user owns. Keeping that authorization boundary outside this storage
        class lets the student service and faculty portal share one SQLite file.
        """
        if not exam_ids:
            return []
        limit = max(1, min(int(limit), 100))
        placeholders = ",".join("?" for _ in exam_ids)
        with self._connection() as connection:
            sessions = connection.execute(
                f"SELECT * FROM assessment_sessions WHERE exam_id IN ({placeholders}) "
                "ORDER BY created_at DESC LIMIT ?",
                (*exam_ids, limit),
            ).fetchall()
            output = []
            for session_row in sessions:
                turns = connection.execute(
                    "SELECT question_id, turn_number, prompt, transcript, action, "
                    "next_prompt, created_at FROM assessment_turns "
                    "WHERE session_id = ? ORDER BY turn_number",
                    (session_row["id"],),
                ).fetchall()
                messages = []
                for turn in turns:
                    messages.extend(
                        [
                            {
                                "speaker": "examiner",
                                "text": str(turn["prompt"]),
                                "timestamp": str(turn["created_at"]),
                                "question_id": str(turn["question_id"]),
                                "turn_number": int(turn["turn_number"]),
                            },
                            {
                                "speaker": "student",
                                "text": str(turn["transcript"]),
                                "timestamp": str(turn["created_at"]),
                                "question_id": str(turn["question_id"]),
                                "turn_number": int(turn["turn_number"]),
                                "action": str(turn["action"]),
                            },
                        ]
                    )
                item = dict(session_row)
                item["completed"] = bool(item["completed"])
                item["messages"] = messages
                item["turn_count"] = len(turns)
                output.append(item)
        return output
