"""Single relational store and adapters for the pre-ERD application API.

SQLite views expose the old column names; all authoritative rows live in the
ERD tables. No changes to passwords, API payloads, or grading are required.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 2


def database_path() -> Path:
    return Path(os.environ.get("APP_DB_PATH", os.environ.get(
        "DB_PATH", ROOT / "runtime" / "assessment.sqlite3"))).expanduser().resolve()


def journal_mode() -> str:
    mode = os.environ.get('APP_DB_JOURNAL_MODE', 'DELETE' if os.name == 'nt' else 'WAL').upper()
    if mode not in {'DELETE','WAL'}:
        raise ValueError('APP_DB_JOURNAL_MODE must be DELETE or WAL')
    return mode


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(path or database_path(), timeout=30, factory=Connection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS "USER" (
 UserID INTEGER PRIMARY KEY AUTOINCREMENT, UserName TEXT UNIQUE NOT NULL,
 PasswordHash TEXT NOT NULL, Role TEXT NOT NULL CHECK(Role IN ('faculty','student')),
 DisplayName TEXT NOT NULL, CreatedAt TEXT NOT NULL, Email TEXT, FirstName TEXT, LastName TEXT);
CREATE TABLE IF NOT EXISTS AUTH_SESSION (
 TokenHash TEXT PRIMARY KEY, UserID INTEGER NOT NULL REFERENCES "USER" ON DELETE CASCADE, ExpiresAt REAL NOT NULL);
CREATE TABLE IF NOT EXISTS DEPARTMENT (
 DepartmentID TEXT PRIMARY KEY, DepartmentName TEXT NOT NULL, DepartmentCode TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS USER_DEPART (
 UserID INTEGER REFERENCES "USER" ON DELETE CASCADE,
 DepartmentID TEXT REFERENCES DEPARTMENT ON DELETE CASCADE, PRIMARY KEY(UserID,DepartmentID));
CREATE TABLE IF NOT EXISTS COURSE (
 CourseID TEXT PRIMARY KEY, UserID INTEGER NOT NULL REFERENCES "USER",
 DepartmentID TEXT REFERENCES DEPARTMENT, CourseCode TEXT NOT NULL,
 CourseName TEXT NOT NULL, CourseDescription TEXT, Term TEXT, CreatedAt TEXT);
CREATE TABLE IF NOT EXISTS USER_COURSE (
 UserID INTEGER REFERENCES "USER" ON DELETE CASCADE,
 CourseID TEXT REFERENCES COURSE ON DELETE CASCADE, PRIMARY KEY(UserID,CourseID));
CREATE TABLE IF NOT EXISTS AVATAR (
 AvatarID TEXT PRIMARY KEY, UserID INTEGER NOT NULL UNIQUE REFERENCES "USER",
 FaceImagePath TEXT, VoiceSamplePath TEXT, MediaVersion TEXT NOT NULL,
 UpdatedAt TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS COURSE_DOC (
 DocumentID TEXT PRIMARY KEY, CourseID TEXT REFERENCES COURSE ON DELETE CASCADE,
 DocumentName TEXT, FilePath TEXT,
 FileType TEXT, UploadedAt TEXT, ProcessingStatus TEXT DEFAULT 'processed',
 Characters INTEGER, FileSize INTEGER, RelativePath TEXT);
CREATE TABLE IF NOT EXISTS DOC_CHUNKS (
 DocChunkID INTEGER PRIMARY KEY AUTOINCREMENT, DocumentID TEXT REFERENCES COURSE_DOC ON DELETE CASCADE,
 Idx INTEGER, Text TEXT, UNIQUE(DocumentID,Idx));
CREATE TABLE IF NOT EXISTS EXAM (
 ExamID TEXT PRIMARY KEY, CourseID TEXT REFERENCES COURSE ON DELETE SET NULL,
 ExamTitle TEXT, ExamDescription TEXT, ExamStatus TEXT, TimeLimit INTEGER,
 CreatedAt TEXT, PublishedAt TEXT, PromptInstructions TEXT, SettingsJSON TEXT,
 LegacyCourse TEXT, UserID INTEGER REFERENCES "USER", MediaVersion TEXT, DeletedAt TEXT);
CREATE TABLE IF NOT EXISTS EXAM_DOC (
 ExamID TEXT REFERENCES EXAM ON DELETE CASCADE,
 DocumentID TEXT REFERENCES COURSE_DOC ON DELETE CASCADE, PRIMARY KEY(ExamID,DocumentID));
CREATE TABLE IF NOT EXISTS EXAM_PUBLICATION (
 ExamID TEXT PRIMARY KEY REFERENCES EXAM ON DELETE CASCADE,
 PublishedAt TEXT NOT NULL, PayloadJSON TEXT NOT NULL CHECK(json_valid(PayloadJSON)));
CREATE TABLE IF NOT EXISTS QUESTION_BANK (
 QuestionID TEXT PRIMARY KEY, ExamID TEXT REFERENCES EXAM ON DELETE CASCADE,
 ExternalQuestionID TEXT NOT NULL, QuestionText TEXT NOT NULL, QuestionSource TEXT,
 SequenceNumber INTEGER NOT NULL, QuestionData TEXT NOT NULL,
 IsActive INTEGER NOT NULL DEFAULT 1 CHECK(IsActive IN (0,1)),
 UNIQUE(ExamID,ExternalQuestionID));
CREATE TABLE IF NOT EXISTS "SESSION" (
 SessionID TEXT PRIMARY KEY, UserID INTEGER REFERENCES "USER" ON DELETE SET NULL,
 ExamID TEXT REFERENCES EXAM ON DELETE SET NULL, CourseID TEXT REFERENCES COURSE ON DELETE SET NULL,
 StartTime TEXT NOT NULL, EndTime TEXT, SessionStatus TEXT NOT NULL DEFAULT 'active',
 QuestionIndex INTEGER NOT NULL DEFAULT 0, FollowUpCount INTEGER NOT NULL DEFAULT 0,
 CurrentPrompt TEXT NOT NULL DEFAULT '', UpdatedAt TEXT NOT NULL,
 LegacyCourseID TEXT, LegacyExamID TEXT, LegacyStudentID INTEGER,
 StudentUserName TEXT, StudentName TEXT);
CREATE TABLE IF NOT EXISTS INTERACTION (
 InteractionID TEXT PRIMARY KEY, SessionID TEXT NOT NULL REFERENCES "SESSION" ON DELETE CASCADE,
 QuestionID TEXT NOT NULL REFERENCES QUESTION_BANK, ActualQuestion TEXT NOT NULL,
 SequenceNumber INTEGER NOT NULL, AskedAt TEXT NOT NULL, NextAction TEXT NOT NULL,
 NextPrompt TEXT NOT NULL DEFAULT '', RetrievedJSON TEXT NOT NULL DEFAULT '[]',
 UNIQUE(SessionID,SequenceNumber));
CREATE TABLE IF NOT EXISTS RESPONSE (
 ResponseID TEXT PRIMARY KEY, InteractionID TEXT NOT NULL UNIQUE REFERENCES INTERACTION ON DELETE CASCADE,
 AnsweredAt TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS RESP_TRANS (
 TranscriptID TEXT PRIMARY KEY, ResponseID TEXT UNIQUE NOT NULL REFERENCES RESPONSE ON DELETE CASCADE,
 TranscriptText TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS RESP_REC (
 RecordingID TEXT PRIMARY KEY, ResponseID TEXT UNIQUE NOT NULL REFERENCES RESPONSE ON DELETE CASCADE,
 AudioFilePath TEXT NOT NULL, Duration REAL, FileFormat TEXT);
CREATE TABLE IF NOT EXISTS EVALUATION (
 EvaluationID TEXT PRIMARY KEY, ResponseID TEXT UNIQUE NOT NULL REFERENCES RESPONSE ON DELETE CASCADE,
 Rating REAL, Feedback TEXT, EvaluationJSON TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS session_exam_start ON "SESSION"(ExamID,StartTime DESC);
CREATE INDEX IF NOT EXISTS interaction_question ON INTERACTION(QuestionID);
'''

# (compatibility name, canonical table, old-to-new columns, primary key)
MAPPINGS = [
 ('users','USER', {'id':'UserID','username':'UserName','display_name':'DisplayName','role':'Role','pw_hash':'PasswordHash','created_at':'CreatedAt'}, 'id'),
 ('sessions','AUTH_SESSION', {'token_hash':'TokenHash','user_id':'UserID','expires_at':'ExpiresAt'}, 'token_hash'),
 ('courses','COURSE', {'id':'CourseID','owner_id':'UserID','code':'CourseCode','name':'CourseName','term':'Term','created_at':'CreatedAt'}, 'id'),
 ('materials','COURSE_DOC', {'id':'DocumentID','filename':'DocumentName','uploaded_at':'UploadedAt','characters':'Characters','course_id':'CourseID','size':'FileSize','relative_path':'RelativePath','storage_path':'FilePath'}, 'id'),
 ('chunks','DOC_CHUNKS', {'id':'DocChunkID','material_id':'DocumentID','idx':'Idx','text':'Text'}, 'id'),
]


def _simple_view(c, name, table, columns, pk):
    select = ','.join(f'"{new}" AS "{old}"' for old,new in columns.items())
    c.execute(f'CREATE VIEW IF NOT EXISTS "{name}" AS SELECT {select} FROM "{table}"')
    names = ','.join(f'"{value}"' for value in columns.values())
    values = ','.join(f'NEW."{key}"' for key in columns)
    assignments = ','.join(f'"{new}"=NEW."{old}"' for old,new in columns.items())
    for op, body in (
        ('INSERT',f'INSERT INTO "{table}" ({names}) VALUES ({values});'),
        ('UPDATE',f'UPDATE "{table}" SET {assignments} WHERE "{columns[pk]}"=OLD."{pk}";'),
        ('DELETE',f'DELETE FROM "{table}" WHERE "{columns[pk]}"=OLD."{pk}";'),
    ):
        c.execute(f'CREATE TRIGGER IF NOT EXISTS "compat_{name}_{op}" INSTEAD OF {op} ON "{name}" BEGIN {body} END')


EXAM_VIEW = '''
CREATE VIEW IF NOT EXISTS exams AS SELECT ExamID id, LegacyCourse course, ExamTitle title,
 SettingsJSON settings,
 (SELECT json_group_array(json(QuestionData)) FROM
   (SELECT QuestionData FROM QUESTION_BANK WHERE ExamID=e.ExamID AND IsActive=1 ORDER BY SequenceNumber)) questions,
 ExamStatus status, CreatedAt created_at, PublishedAt published_at, CourseID course_id,
 UserID professor_id, MediaVersion media_version FROM EXAM e WHERE DeletedAt IS NULL;
CREATE TRIGGER IF NOT EXISTS compat_exams_delete INSTEAD OF DELETE ON exams
 BEGIN UPDATE EXAM SET DeletedAt=CURRENT_TIMESTAMP WHERE ExamID=OLD.id; END;
'''


def _exam_triggers(c):
    for op in ('INSERT','UPDATE'):
        c.executescript(f'''
        CREATE TRIGGER IF NOT EXISTS compat_exams_{op} INSTEAD OF {op} ON exams BEGIN
          INSERT INTO EXAM(ExamID,CourseID,ExamTitle,ExamStatus,CreatedAt,PublishedAt,SettingsJSON,LegacyCourse,UserID,MediaVersion,TimeLimit,PromptInstructions)
          VALUES(NEW.id,NEW.course_id,NEW.title,NEW.status,NEW.created_at,NEW.published_at,NEW.settings,NEW.course,NEW.professor_id,NEW.media_version,
            json_extract(NEW.settings,'$.seconds_per_question'),json_extract(NEW.settings,'$.prompt_instructions'))
          ON CONFLICT(ExamID) DO UPDATE SET CourseID=excluded.CourseID,ExamTitle=excluded.ExamTitle,
            ExamStatus=excluded.ExamStatus,CreatedAt=excluded.CreatedAt,PublishedAt=excluded.PublishedAt,
            SettingsJSON=excluded.SettingsJSON,LegacyCourse=excluded.LegacyCourse,UserID=excluded.UserID,
            MediaVersion=excluded.MediaVersion,TimeLimit=excluded.TimeLimit,PromptInstructions=excluded.PromptInstructions;
          UPDATE QUESTION_BANK SET IsActive=0 WHERE ExamID=NEW.id;
          INSERT INTO QUESTION_BANK(QuestionID,ExamID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
          SELECT NEW.id||':'||json_extract(value,'$.id'),NEW.id,json_extract(value,'$.id'),
            coalesce(json_extract(value,'$.question'),json_extract(value,'$.prompt'),''),
            CASE WHEN json_extract(value,'$.source_excerpt') LIKE 'Imported from%' THEN 'imported' ELSE 'generated' END,
            CAST(key AS INTEGER),value,1 FROM json_each(coalesce(NEW.questions,'[]')) WHERE 1
          ON CONFLICT(QuestionID) DO UPDATE SET QuestionText=excluded.QuestionText,QuestionSource=excluded.QuestionSource,
            SequenceNumber=excluded.SequenceNumber,QuestionData=excluded.QuestionData,IsActive=1;
          DELETE FROM EXAM_DOC WHERE ExamID=NEW.id;
          INSERT INTO EXAM_DOC SELECT NEW.id,value FROM json_each(NEW.settings,'$.material_ids')
            WHERE value IN (SELECT DocumentID FROM COURSE_DOC);
        END;''')


SESSION_VIEWS = '''
CREATE VIEW IF NOT EXISTS assessment_sessions AS SELECT SessionID id,
 coalesce(CourseID,LegacyCourseID) course_id,coalesce(ExamID,LegacyExamID) exam_id,
 coalesce(UserID,LegacyStudentID) student_id,StudentUserName student_username,StudentName student_name,
 QuestionIndex question_index,FollowUpCount follow_up_count,SessionStatus='completed' completed,
 CurrentPrompt current_prompt,StartTime created_at,UpdatedAt updated_at,EndTime completed_at FROM "SESSION";
CREATE TRIGGER IF NOT EXISTS compat_assessment_sessions_insert INSTEAD OF INSERT ON assessment_sessions BEGIN
 INSERT INTO "SESSION"(SessionID,UserID,ExamID,CourseID,StartTime,EndTime,SessionStatus,QuestionIndex,FollowUpCount,CurrentPrompt,UpdatedAt,LegacyCourseID,LegacyExamID,LegacyStudentID,StudentUserName,StudentName)
 VALUES(NEW.id,(SELECT UserID FROM "USER" WHERE UserID=NEW.student_id),
 (SELECT ExamID FROM EXAM WHERE ExamID=NEW.exam_id),(SELECT CourseID FROM COURSE WHERE CourseID=NEW.course_id),
 NEW.created_at,NEW.completed_at,CASE WHEN NEW.completed THEN 'completed' ELSE 'active' END,
 coalesce(NEW.question_index,0),coalesce(NEW.follow_up_count,0),coalesce(NEW.current_prompt,''),NEW.updated_at,
 NEW.course_id,NEW.exam_id,NEW.student_id,NEW.student_username,NEW.student_name);
 END;
CREATE TRIGGER IF NOT EXISTS compat_assessment_sessions_update INSTEAD OF UPDATE ON assessment_sessions BEGIN
 UPDATE "SESSION" SET QuestionIndex=NEW.question_index,FollowUpCount=NEW.follow_up_count,
 SessionStatus=CASE WHEN NEW.completed THEN 'completed' ELSE 'active' END,CurrentPrompt=NEW.current_prompt,
 UpdatedAt=NEW.updated_at,EndTime=NEW.completed_at WHERE SessionID=OLD.id;
 END;
CREATE VIEW IF NOT EXISTS assessment_turns AS SELECT i.InteractionID id,i.SessionID session_id,
 q.ExternalQuestionID question_id,i.SequenceNumber turn_number,i.ActualQuestion prompt,t.TranscriptText transcript,
 e.EvaluationJSON evaluation_json,i.RetrievedJSON retrieved_json,i.NextAction action,i.NextPrompt next_prompt,r.AnsweredAt created_at
 FROM INTERACTION i JOIN QUESTION_BANK q ON q.QuestionID=i.QuestionID
 JOIN RESPONSE r ON r.InteractionID=i.InteractionID JOIN RESP_TRANS t ON t.ResponseID=r.ResponseID
 JOIN EVALUATION e ON e.ResponseID=r.ResponseID;
CREATE TRIGGER IF NOT EXISTS compat_assessment_turns_insert INSTEAD OF INSERT ON assessment_turns BEGIN
 INSERT INTO QUESTION_BANK(QuestionID,ExamID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
 SELECT coalesce(s.ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id,s.ExamID,NEW.question_id,NEW.prompt,'legacy',NEW.turn_number,
 json_object('id',NEW.question_id,'question',NEW.prompt),0 FROM "SESSION" s WHERE s.SessionID=NEW.session_id
 ON CONFLICT(QuestionID) DO NOTHING;
 INSERT INTO INTERACTION VALUES(NEW.id,NEW.session_id,
 (SELECT coalesce(ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id FROM "SESSION" WHERE SessionID=NEW.session_id),
 NEW.prompt,NEW.turn_number,NEW.created_at,NEW.action,coalesce(NEW.next_prompt,''),NEW.retrieved_json);
 INSERT INTO RESPONSE VALUES(NEW.id,NEW.id,NEW.created_at);
 INSERT INTO RESP_TRANS VALUES(NEW.id,NEW.id,NEW.transcript);
 INSERT INTO EVALUATION VALUES(NEW.id,NEW.id,json_extract(NEW.evaluation_json,'$.rating'),json_extract(NEW.evaluation_json,'$.feedback'),NEW.evaluation_json);
 END;
CREATE VIEW IF NOT EXISTS professor_media AS SELECT UserID user_id,MediaVersion version,UpdatedAt updated_at FROM AVATAR;
'''


def initialize_database(path: Path | None = None) -> None:
    """Initialize an empty/unified file; never silently overwrite a legacy file."""
    path = Path(path or database_path())
    if not path.exists() and path.resolve() == database_path() and path.resolve() == (ROOT / "runtime" / "assessment.sqlite3").resolve() and (ROOT / "faculty-portal" / "exam_builder.db").is_file():
        raise RuntimeError("Start through pipeline.py to migrate the legacy databases first")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        with connect(path) as probe:
            if probe.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
                versions = [r[0] for r in probe.execute('SELECT version FROM schema_migrations')]
            else:
                versions = []
        if versions == [1]:
            from .schema_upgrade import upgrade_v1
            upgrade_v1(path)
    with connect(path) as c:
        legacy = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users','courses','assessment_sessions')").fetchall()
        if legacy:
            raise RuntimeError('Legacy database requires scripts/migrate-database.py before startup: ' + str(path))
        c.execute(f'PRAGMA journal_mode={journal_mode()}')
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
            versions = [r[0] for r in c.execute('SELECT version FROM schema_migrations')]
            if versions and max(versions) > SCHEMA_VERSION:
                raise RuntimeError('Database schema is newer than this application')
            if SCHEMA_VERSION in versions:
                _repair_missing_surnames(c)
                return
        c.executescript(SCHEMA)
        for mapping in MAPPINGS:
            _simple_view(c, *mapping)
        c.executescript(EXAM_VIEW)
        _exam_triggers(c)
        c.executescript(SESSION_VIEWS)
        c.execute('INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)',(SCHEMA_VERSION,))


def _repair_missing_surnames(c) -> None:
    """Repair incomplete full-name accounts without replacing explicit surnames."""
    for row in c.execute('''SELECT UserID,UserName,DisplayName,FirstName FROM "USER"
                           WHERE trim(coalesce(LastName,''))='' ''').fetchall():
        first = (row['FirstName'] or '').strip()
        full = first if len(first.split()) > 1 else ' '.join((row['DisplayName'] or '').split())
        parts = full.split(maxsplit=1)
        if len(parts) != 2 or full == row['UserName']:
            continue
        if first and first not in (full,parts[0]):
            continue
        c.execute('UPDATE "USER" SET FirstName=?,LastName=? WHERE UserID=?',
                  (parts[0],parts[1],row['UserID']))


def save_avatar(c, user_id: int, version: str, updated_at: str) -> None:
    """Replace the user's single avatar; content paths still invalidate caches."""
    from .profiles import profile_paths
    photo, voice = profile_paths(user_id, version)
    c.execute('''INSERT INTO AVATAR(AvatarID,UserID,FaceImagePath,VoiceSamplePath,MediaVersion,UpdatedAt)
      VALUES(?,?,?,?,?,?) ON CONFLICT(UserID) DO UPDATE SET
      FaceImagePath=excluded.FaceImagePath,VoiceSamplePath=excluded.VoiceSamplePath,
      MediaVersion=excluded.MediaVersion,UpdatedAt=excluded.UpdatedAt''',
      (f'avatar:{user_id}',user_id,str(photo),str(voice),version,updated_at))


def save_publication(c, exam: dict) -> None:
    import json
    c.execute('''INSERT INTO EXAM_PUBLICATION VALUES(?,?,?) ON CONFLICT(ExamID)
      DO UPDATE SET PublishedAt=excluded.PublishedAt,PayloadJSON=excluded.PayloadJSON''',
      (exam['exam_id'],exam['published_at'],json.dumps(exam)))


def read_publication(c, exam_id: str) -> dict:
    import json
    row = c.execute('''SELECT p.PayloadJSON FROM EXAM_PUBLICATION p JOIN EXAM e ON e.ExamID=p.ExamID
      WHERE p.ExamID=? AND e.DeletedAt IS NULL AND e.ExamStatus='published' ''',(exam_id,)).fetchone()
    if row is None:
        raise KeyError(exam_id)
    exam = json.loads(row[0])
    avatar = c.execute('SELECT UserID,MediaVersion FROM AVATAR WHERE UserID=?',
                       (exam.get('professor_id'),)).fetchone()
    if 'professor_id' in exam or 'examiner' in exam:
        exam['examiner'] = {'professor_id': avatar[0], 'media_version': avatar[1]} if avatar else None
    return exam
