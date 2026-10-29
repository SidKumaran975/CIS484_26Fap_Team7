import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .database import initialize_database, connect


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._initialize()

    def _connect(self):
        return connect(self.path)

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        initialize_database(self.path)

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
        recording: dict | None = None,
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
            if recording:
                connection.execute(
                    'INSERT INTO RESP_REC(RecordingID,ResponseID,AudioFilePath,Duration,FileFormat) VALUES(?,?,?,?,?)',
                    (turn_id,turn_id,recording['path'],recording.get('duration'),recording.get('format')),
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
                    "SELECT t.question_id, t.turn_number, t.prompt, t.transcript, t.action, "
                    "t.next_prompt, t.created_at, r.RecordingID AS recording_id, "
                    "r.FileFormat AS recording_format, r.Duration AS recording_duration "
                    "FROM assessment_turns t LEFT JOIN RESP_REC r ON r.ResponseID=t.id "
                    "WHERE t.session_id = ? ORDER BY t.turn_number",
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
                                "recording": {
                                    "id": turn["recording_id"],
                                    "url": f"/api/recordings/{turn['recording_id']}",
                                    "format": turn["recording_format"],
                                    "duration": turn["recording_duration"],
                                } if turn["recording_id"] else None,
                            },
                        ]
                    )
                item = dict(session_row)
                item["completed"] = bool(item["completed"])
                item["messages"] = messages
                item["turn_count"] = len(turns)
                output.append(item)
        return output
