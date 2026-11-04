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

    def prepare_interaction(self, session_id, question_id, prompt, essential_question=None):
        """Create the exchange before playback; follow-ups have their own concept."""
        with self.lock, self._connection() as c:
            pending = c.execute('SELECT InteractionID FROM INTERACTION WHERE SessionID=? AND Evaluation IS NULL', (session_id,)).fetchone()
            if pending:
                return pending[0]
            session = c.execute('SELECT * FROM "SESSION" WHERE SessionID=?', (session_id,)).fetchone()
            parent = (session['ExamID'] or 'legacy:' + session_id) + ':' + question_id
            c.execute('''INSERT OR IGNORE INTO QUEST_ESS(QuestionID,ExamID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
                VALUES(?,?,?,?,?,0,?,0)''', (parent, session['ExamID'], question_id, prompt, 'legacy', json.dumps({'id': question_id, 'question': prompt})))
            interaction_id = str(uuid.uuid4())
            essential_id = ('followup:' if essential_question else 'snapshot:') + interaction_id
            bank = c.execute('SELECT BankID FROM QUEST_ESS WHERE QuestionID=?',(parent,)).fetchone()[0]
            essential_text = essential_question or prompt
            c.execute('''INSERT INTO QUEST_ESS(QuestionID,ExternalQuestionID,QuestionText,QuestionSource,BankID,SequenceNumber,QuestionData,IsActive)
                VALUES(?,?,?,?,?,0,?,0)''', (essential_id,question_id,essential_text,'follow_up' if essential_question else 'publication_snapshot',
                    None if essential_question else bank,json.dumps({'question':essential_text})))
            number = c.execute('SELECT count(*)+1 FROM INTERACTION WHERE SessionID=?',(session_id,)).fetchone()[0]
            c.execute('''INSERT INTO INTERACTION(InteractionID,SessionID,QuestionID,ParentQuestionID,ActualQuestionTxt,SequenceNumber,StartTime,NextAction)
                VALUES(?,?,?,?,?,?,?,'pending')''', (interaction_id,session_id,essential_id,parent,prompt,number,''))
            return interaction_id

    def question_media(self, session_id, path):
        with self._connection() as c:
            c.execute('UPDATE INTERACTION SET ActualQuestionVid=? WHERE SessionID=? AND Evaluation IS NULL',(path,session_id))

    def timing_event(self, session_id, interaction_id, event, timestamp):
        column = {'question_start':'StartTime','question_end':'QuestionEndTime'}[event]
        with self._connection() as c:
            row = c.execute('SELECT * FROM INTERACTION WHERE InteractionID=? AND SessionID=?',(interaction_id,session_id)).fetchone()
            if row is None or row['Evaluation'] is not None:
                raise ValueError('This interaction is not active')
            if event == 'question_end' and not row['StartTime']:
                raise ValueError('Question playback has not started')
            if event == 'question_end' and timestamp < row['StartTime']:
                raise ValueError('Question end precedes question start')
            c.execute(f'UPDATE INTERACTION SET {column}=? WHERE InteractionID=? AND coalesce({column},\'\')=\'\'',(timestamp,interaction_id))

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
            pending = connection.execute('SELECT * FROM INTERACTION WHERE SessionID=? AND Evaluation IS NULL',(session_id,)).fetchone()
            if recording and recording.get('interaction_id') and (not pending or pending['InteractionID'] != recording['interaction_id']):
                raise ValueError('This interaction has already been answered')
            if recording and recording.get('end_time'):
                now = max(now, recording['end_time'])
            if pending:
                turn_id = pending['InteractionID']
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM assessment_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not pending:
                self._insert_legacy_turn(connection, turn_id, session_id, question_id, prompt, transcript, evaluation, retrieved, action, next_prompt, now, int(row['count'])+1)
            else:
                if recording and (not pending['StartTime'] or not pending['QuestionEndTime']):
                    raise ValueError('Question playback timestamps are required')
                connection.execute('''INSERT OR IGNORE INTO RECORDING(RecordingID,SessionID,StartTime) SELECT SessionID,SessionID,StartTime FROM "SESSION" WHERE SessionID=?''',(session_id,))
                connection.execute('INSERT INTO CLIP_RESP(RespClipID,InteractionID,RecordingID) VALUES(?,?,?)',(turn_id,turn_id,session_id))
                connection.execute('INSERT INTO CLIP_TRANS VALUES(?,?,?)',(turn_id,turn_id,transcript))
                connection.execute('''UPDATE INTERACTION SET Evaluation=?,PickedTransID=?,NextAction=?,NextPrompt=?,RetrievedJSON=?,EndTime=? WHERE InteractionID=?''',
                    (json.dumps(evaluation),turn_id,action,next_prompt,json.dumps(retrieved),now,turn_id))
            connection.execute('UPDATE CLIP_RESP SET EndTime=? WHERE RespClipID=?',(now,turn_id))
            if recording:
                start, end = recording.get('start_time'), recording.get('end_time')
                if start and end and (end < start or (pending and start < pending['QuestionEndTime'])):
                    raise ValueError('Response timestamps are out of order')
                connection.execute('''UPDATE CLIP_RESP SET AudioFilePath=?,Duration=?,FileFormat=?,StartTime=?,EndTime=coalesce(?,EndTime) WHERE RespClipID=?''',
                    (recording['path'],recording.get('duration'),recording.get('format'),start,end,turn_id))
            connection.execute(
                "UPDATE assessment_sessions SET question_index = ?, "
                "follow_up_count = ?, completed = ?, current_prompt = ?, "
                "updated_at = ?, completed_at = CASE WHEN ? THEN ? ELSE completed_at END "
                "WHERE id = ?",
                (question_index,follow_up_count,int(completed),next_prompt,now,int(completed),now,session_id),
            )
        return turn_id

    @staticmethod
    def _insert_legacy_turn(connection, turn_id, session_id, question_id, prompt, transcript, evaluation, retrieved, action, next_prompt, now, number):
        connection.execute(
            "INSERT INTO assessment_turns "
            "(id, session_id, question_id, turn_number, prompt, transcript, "
            "evaluation_json, retrieved_json, action, next_prompt, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn_id,
                session_id,
                question_id,
                number,
                prompt,
                transcript,
                json.dumps(evaluation),
                json.dumps(retrieved),
                action,
                next_prompt,
                now,
            ),
        )

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
                    "r.FileFormat AS recording_format, r.Duration AS recording_duration, "
                    "i.Evaluation, q.QuestionText essential_question, i.StartTime, i.QuestionEndTime, i.EndTime, "
                    "clip.StartTime response_start,clip.EndTime response_end,i.ActualQuestionVid,i.InteractionID "
                    "FROM assessment_turns t LEFT JOIN RESP_REC r ON r.ResponseID=t.id "
                    "JOIN INTERACTION i ON i.InteractionID=t.id JOIN QUEST_ESS q ON q.QuestionID=i.QuestionID "
                    "LEFT JOIN CLIP_RESP clip ON clip.InteractionID=i.InteractionID "
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
                                "essential_question": turn['essential_question'],
                                "start_time": turn['StartTime'],
                                "question_end_time": turn['QuestionEndTime'],
                                "video_url": f"/api/question-videos/{turn['InteractionID']}" if turn['ActualQuestionVid'] else None,
                            },
                            {
                                "speaker": "student",
                                "text": str(turn["transcript"]),
                                "timestamp": str(turn["created_at"]),
                                "question_id": str(turn["question_id"]),
                                "turn_number": int(turn["turn_number"]),
                                "action": str(turn["action"]),
                                "evaluation": json.loads(turn['Evaluation'] or '{}'),
                                "start_time": turn['response_start'],
                                "end_time": turn['response_end'],
                                "interaction_end_time": turn['EndTime'],
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
                item['status'] = connection.execute('SELECT SessionStatus FROM "SESSION" WHERE SessionID=?',(session_row['id'],)).fetchone()[0]
                item["messages"] = messages
                item["turn_count"] = len(turns)
                recordings = connection.execute('SELECT RecordingID,StartTime,EndTime,RecordingStatus,RecordingPath FROM RECORDING WHERE SessionID=?',(session_row['id'],)).fetchall()
                item['recordings'] = [{'id':r['RecordingID'],'start_time':r['StartTime'],'end_time':r['EndTime'],'status':r['RecordingStatus'],
                    'url':f"/api/full-recordings/{r['RecordingID']}" if r['RecordingPath'] else None} for r in recordings]
                output.append(item)
        return output
