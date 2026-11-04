"""Transactional, backed-up migration to the recording/interaction ERD."""
import sqlite3
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


SQL = '''
CREATE TABLE STUDENT (
 StudentID INTEGER PRIMARY KEY REFERENCES "USER" ON DELETE CASCADE,
 EnrollmentDate TEXT, AcademicLevel TEXT, Major TEXT, EnrollmentStatus TEXT);
CREATE TABLE INSTRUCTOR (
 InstructorID INTEGER PRIMARY KEY REFERENCES "USER" ON DELETE CASCADE,
 DepartmentID TEXT REFERENCES DEPARTMENT, FaceImagePath TEXT, VoiceSamplePath TEXT,
 MediaVersion TEXT, UpdatedAt TEXT);
INSERT INTO STUDENT(StudentID) SELECT UserID FROM "USER" WHERE Role='student';
INSERT INTO INSTRUCTOR(InstructorID,DepartmentID)
 SELECT UserID,(SELECT DepartmentID FROM USER_DEPART d WHERE d.UserID=u.UserID ORDER BY DepartmentID LIMIT 1)
 FROM "USER" u WHERE Role='faculty';
UPDATE INSTRUCTOR SET (FaceImagePath,VoiceSamplePath,MediaVersion,UpdatedAt)=
 (SELECT FaceImagePath,VoiceSamplePath,MediaVersion,UpdatedAt FROM AVATAR WHERE UserID=InstructorID);
DROP VIEW professor_media;
DROP TABLE AVATAR;
CREATE VIEW AVATAR AS SELECT 'avatar:'||InstructorID AvatarID,InstructorID UserID,
 FaceImagePath,VoiceSamplePath,MediaVersion,UpdatedAt FROM INSTRUCTOR WHERE MediaVersion IS NOT NULL;
CREATE VIEW professor_media AS SELECT InstructorID user_id,MediaVersion version,UpdatedAt updated_at
 FROM INSTRUCTOR WHERE MediaVersion IS NOT NULL;
CREATE TRIGGER user_profile_insert AFTER INSERT ON "USER" BEGIN
 INSERT INTO STUDENT(StudentID) SELECT NEW.UserID WHERE NEW.Role='student';
 INSERT INTO INSTRUCTOR(InstructorID) SELECT NEW.UserID WHERE NEW.Role='faculty';
END;
CREATE TABLE SECTION (
 SectionID TEXT PRIMARY KEY, InstructorID INTEGER REFERENCES INSTRUCTOR,
 CourseID TEXT NOT NULL REFERENCES COURSE ON DELETE CASCADE, SectionNumber TEXT NOT NULL);
CREATE TABLE STUDENT_SEC (
 StudentID INTEGER REFERENCES STUDENT ON DELETE CASCADE,
 SectionID TEXT REFERENCES SECTION ON DELETE CASCADE, PRIMARY KEY(StudentID,SectionID));
INSERT INTO SECTION SELECT 'legacy:'||CourseID,UserID,CourseID,'legacy-unassigned' FROM COURSE;
INSERT INTO STUDENT_SEC SELECT UserID,'legacy:'||CourseID FROM USER_COURSE;
CREATE TRIGGER course_section_insert AFTER INSERT ON COURSE BEGIN
 INSERT INTO SECTION VALUES('legacy:'||NEW.CourseID,NEW.UserID,NEW.CourseID,'legacy-unassigned'); END;
CREATE TRIGGER enrollment_section_insert AFTER INSERT ON USER_COURSE BEGIN
 INSERT OR IGNORE INTO STUDENT_SEC VALUES(NEW.UserID,'legacy:'||NEW.CourseID); END;
CREATE TRIGGER enrollment_section_delete AFTER DELETE ON USER_COURSE BEGIN
 DELETE FROM STUDENT_SEC WHERE StudentID=OLD.UserID AND SectionID='legacy:'||OLD.CourseID; END;
ALTER TABLE "SESSION" ADD COLUMN StudentID INTEGER REFERENCES STUDENT;
ALTER TABLE "SESSION" ADD COLUMN InstructorID INTEGER REFERENCES INSTRUCTOR;
UPDATE "SESSION" SET StudentID=(SELECT StudentID FROM STUDENT WHERE StudentID="SESSION".UserID),
 InstructorID=(SELECT coalesce(e.UserID,c.UserID) FROM EXAM e LEFT JOIN COURSE c ON c.CourseID=e.CourseID WHERE e.ExamID="SESSION".ExamID);
CREATE TRIGGER session_profile_insert AFTER INSERT ON "SESSION" BEGIN
 UPDATE "SESSION" SET StudentID=(SELECT StudentID FROM STUDENT WHERE StudentID=NEW.UserID),
 InstructorID=(SELECT coalesce(e.UserID,c.UserID) FROM EXAM e LEFT JOIN COURSE c ON c.CourseID=e.CourseID WHERE e.ExamID=NEW.ExamID)
 WHERE SessionID=NEW.SessionID; END;
CREATE TABLE QUEST_BANK (
 BankID TEXT PRIMARY KEY, ExamID TEXT NOT NULL UNIQUE REFERENCES EXAM ON DELETE CASCADE, DocSource TEXT);
INSERT INTO QUEST_BANK SELECT ExamID,ExamID,NULL FROM EXAM;
CREATE TRIGGER exam_bank_insert AFTER INSERT ON EXAM BEGIN
 INSERT INTO QUEST_BANK(BankID,ExamID) VALUES(NEW.ExamID,NEW.ExamID); END;
ALTER TABLE QUESTION_BANK RENAME TO QUEST_ESS;
ALTER TABLE QUEST_ESS ADD COLUMN BankID TEXT REFERENCES QUEST_BANK ON DELETE SET NULL;
UPDATE QUEST_ESS SET BankID=ExamID WHERE ExamID IS NOT NULL;
CREATE TRIGGER essential_bank_insert AFTER INSERT ON QUEST_ESS WHEN NEW.BankID IS NULL AND NEW.ExamID IS NOT NULL BEGIN
 UPDATE QUEST_ESS SET BankID=(SELECT BankID FROM QUEST_BANK WHERE ExamID=NEW.ExamID) WHERE QuestionID=NEW.QuestionID; END;
ALTER TABLE INTERACTION RENAME COLUMN ActualQuestion TO ActualQuestionTxt;
ALTER TABLE INTERACTION RENAME COLUMN AskedAt TO StartTime;
ALTER TABLE INTERACTION ADD COLUMN QuestionEndTime TEXT;
ALTER TABLE INTERACTION ADD COLUMN EndTime TEXT;
ALTER TABLE INTERACTION ADD COLUMN ActualQuestionVid TEXT;
ALTER TABLE INTERACTION ADD COLUMN Evaluation TEXT CHECK(Evaluation IS NULL OR json_valid(Evaluation));
ALTER TABLE INTERACTION ADD COLUMN PickedTransID TEXT REFERENCES CLIP_TRANS(TranscriptID);
ALTER TABLE INTERACTION ADD COLUMN ParentQuestionID TEXT REFERENCES QUEST_ESS(QuestionID);
CREATE TABLE RECORDING (
 RecordingID TEXT PRIMARY KEY, SessionID TEXT NOT NULL REFERENCES "SESSION" ON DELETE CASCADE,
 StartTime TEXT, EndTime TEXT, RecordingPath TEXT,
 RecordingStatus TEXT NOT NULL DEFAULT 'pending', FileFormat TEXT);
CREATE TABLE CLIP_RESP (
 RespClipID TEXT PRIMARY KEY, InteractionID TEXT NOT NULL UNIQUE REFERENCES INTERACTION ON DELETE CASCADE,
 RecordingID TEXT NOT NULL REFERENCES RECORDING ON DELETE CASCADE,
 AudioFilePath TEXT, StartTime TEXT, EndTime TEXT, FileFormat TEXT, Duration REAL);
CREATE TABLE CLIP_TRANS (
 TranscriptID TEXT PRIMARY KEY, RespClipID TEXT NOT NULL REFERENCES CLIP_RESP ON DELETE CASCADE,
 TranscriptText TEXT NOT NULL);
INSERT INTO RECORDING(RecordingID,SessionID,StartTime,EndTime,RecordingStatus)
 SELECT SessionID,SessionID,StartTime,EndTime,'unavailable_legacy' FROM "SESSION";
INSERT INTO CLIP_RESP SELECT r.ResponseID,r.InteractionID,i.SessionID,rec.AudioFilePath,
 NULL,r.AnsweredAt,rec.FileFormat,rec.Duration FROM RESPONSE r JOIN INTERACTION i USING(InteractionID)
 LEFT JOIN RESP_REC rec ON rec.ResponseID=r.ResponseID;
INSERT INTO CLIP_TRANS SELECT TranscriptID,ResponseID,TranscriptText FROM RESP_TRANS;
UPDATE INTERACTION SET Evaluation=(SELECT EvaluationJSON FROM EVALUATION e JOIN RESPONSE r USING(ResponseID) WHERE r.InteractionID=INTERACTION.InteractionID),
 PickedTransID=(SELECT t.TranscriptID FROM RESP_TRANS t JOIN RESPONSE r USING(ResponseID) WHERE r.InteractionID=INTERACTION.InteractionID),
 EndTime=(SELECT AnsweredAt FROM RESPONSE r WHERE r.InteractionID=INTERACTION.InteractionID);
DROP VIEW assessment_turns;
DROP TABLE EVALUATION;
DROP TABLE RESP_TRANS;
DROP TABLE RESP_REC;
DROP TABLE RESPONSE;
CREATE VIEW RESPONSE AS SELECT RespClipID ResponseID,InteractionID,EndTime AnsweredAt FROM CLIP_RESP;
CREATE VIEW RESP_TRANS AS SELECT TranscriptID,RespClipID ResponseID,TranscriptText FROM CLIP_TRANS;
CREATE VIEW RESP_REC AS SELECT RespClipID RecordingID,RespClipID ResponseID,AudioFilePath,Duration,FileFormat
 FROM CLIP_RESP WHERE AudioFilePath IS NOT NULL;
CREATE TRIGGER compat_resp_rec_insert INSTEAD OF INSERT ON RESP_REC BEGIN
 UPDATE CLIP_RESP SET AudioFilePath=NEW.AudioFilePath,Duration=NEW.Duration,FileFormat=NEW.FileFormat
 WHERE RespClipID=NEW.ResponseID; END;
CREATE VIEW EVALUATION AS SELECT InteractionID EvaluationID,c.RespClipID ResponseID,
 json_extract(Evaluation,'$.rating') Rating,json_extract(Evaluation,'$.feedback') Feedback,Evaluation EvaluationJSON
 FROM INTERACTION i JOIN CLIP_RESP c USING(InteractionID) WHERE Evaluation IS NOT NULL;
CREATE VIEW assessment_turns AS SELECT i.InteractionID id,i.SessionID session_id,
 coalesce(parent.ExternalQuestionID,q.ExternalQuestionID) question_id,i.SequenceNumber turn_number,
 i.ActualQuestionTxt prompt,t.TranscriptText transcript,i.Evaluation evaluation_json,
 i.RetrievedJSON retrieved_json,i.NextAction action,i.NextPrompt next_prompt,c.EndTime created_at
 FROM INTERACTION i JOIN QUEST_ESS q ON q.QuestionID=i.QuestionID
 LEFT JOIN QUEST_ESS parent ON parent.QuestionID=i.ParentQuestionID
 JOIN CLIP_RESP c USING(InteractionID) JOIN CLIP_TRANS t ON t.TranscriptID=i.PickedTransID;
CREATE TRIGGER compat_assessment_turns_insert INSTEAD OF INSERT ON assessment_turns BEGIN
 INSERT INTO QUEST_ESS(QuestionID,ExamID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
 SELECT coalesce(s.ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id,s.ExamID,NEW.question_id,NEW.prompt,'legacy',NEW.turn_number,
 json_object('id',NEW.question_id,'question',NEW.prompt),0 FROM "SESSION" s WHERE s.SessionID=NEW.session_id
 ON CONFLICT(QuestionID) DO NOTHING;
 INSERT INTO INTERACTION(InteractionID,SessionID,QuestionID,ActualQuestionTxt,SequenceNumber,StartTime,NextAction,NextPrompt,RetrievedJSON,Evaluation,EndTime)
 VALUES(NEW.id,NEW.session_id,(SELECT coalesce(ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id FROM "SESSION" WHERE SessionID=NEW.session_id),
 NEW.prompt,NEW.turn_number,coalesce(NEW.created_at,''),NEW.action,coalesce(NEW.next_prompt,''),NEW.retrieved_json,NEW.evaluation_json,NEW.created_at);
 INSERT OR IGNORE INTO RECORDING(RecordingID,SessionID,StartTime,RecordingStatus)
 SELECT SessionID,SessionID,StartTime,'pending' FROM "SESSION" WHERE SessionID=NEW.session_id;
 INSERT INTO CLIP_RESP(RespClipID,InteractionID,RecordingID,EndTime) VALUES(NEW.id,NEW.id,NEW.session_id,NEW.created_at);
 INSERT INTO CLIP_TRANS VALUES(NEW.id,NEW.id,NEW.transcript);
 UPDATE INTERACTION SET PickedTransID=NEW.id WHERE InteractionID=NEW.id;
END;
CREATE TRIGGER selected_transcript_insert BEFORE INSERT ON INTERACTION WHEN NEW.PickedTransID IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM CLIP_TRANS t JOIN CLIP_RESP c USING(RespClipID)
 WHERE t.TranscriptID=NEW.PickedTransID AND c.InteractionID=NEW.InteractionID)
 THEN RAISE(ABORT,'Selected transcript belongs to a different interaction') END; END;
CREATE TRIGGER selected_transcript_update BEFORE UPDATE OF PickedTransID ON INTERACTION WHEN NEW.PickedTransID IS NOT NULL BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM CLIP_TRANS t JOIN CLIP_RESP c USING(RespClipID)
 WHERE t.TranscriptID=NEW.PickedTransID AND c.InteractionID=NEW.InteractionID)
 THEN RAISE(ABORT,'Selected transcript belongs to a different interaction') END; END;
'''


def upgrade_v2(path: Path):
    """Stop services before upgrading. Roll back all DDL on validation failure."""
    from .database import connect, _simple_view
    path = Path(path)
    with connect(path) as probe:
        if probe.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] >= 4:
            return
    backup_dir = path.parent / 'database-backups'
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / ('before-erd-v4-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as dest:
        source.backup(dest)
    with connect(path) as c:
        c.execute('PRAGMA foreign_keys=OFF')
        # executescript does not commit a transaction when called once with BEGIN.
        c.executescript('BEGIN IMMEDIATE;\n' + SQL)
        # ALTER TABLE updates exam triggers/views to the canonical table name.
        # Restore the legacy question API as a writable view for old import tools.
        columns = [r[1] for r in c.execute('PRAGMA table_info(QUEST_ESS)') if r[1] != 'BankID']
        _simple_view(c, 'QUESTION_BANK', 'QUEST_ESS', {k:k for k in columns}, 'QuestionID')
        _legacy_essential_questions(c)
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('ERD v3 foreign-key validation failed; migration rolled back')
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('ERD v3 integrity check failed; migration rolled back')
        c.execute('INSERT INTO schema_migrations(version) VALUES(4)')
    return backup


def _legacy_essential_questions(c):
    """Preserve bank concepts; derive old follow-up concepts from prior grading."""
    previous = {}
    rows = c.execute('''SELECT i.*,q.QuestionText,q.ExternalQuestionID,q.BankID FROM INTERACTION i
        JOIN QUEST_ESS q USING(QuestionID) ORDER BY i.SessionID,i.SequenceNumber''').fetchall()
    for row in rows:
        prior = previous.get(row['SessionID'])
        followup = prior and prior['QuestionID'] == row['QuestionID'] and prior['NextAction'] in ('probe','clarify','deepen')
        essential = row['QuestionText']
        if followup:
            evaluation = json.loads(prior['Evaluation'] or '{}')
            concepts = evaluation.get('missing_concepts') or evaluation.get('misconceptions') or []
            essential = evaluation.get('follow_up_essential_question') or ('Explain ' + '; '.join(concepts) + '.' if concepts else row['QuestionText'])
        key = ('followup:' if followup else 'snapshot:') + row['InteractionID']
        c.execute('''INSERT INTO QUEST_ESS(QuestionID,ExternalQuestionID,QuestionText,QuestionSource,BankID,SequenceNumber,QuestionData,IsActive)
            VALUES(?,?,?,?,?,0,?,0)''',(key,row['ExternalQuestionID'],essential,'legacy_follow_up' if followup else 'legacy_snapshot',
                None if followup else row['BankID'],json.dumps({'question':essential})))
        c.execute('UPDATE INTERACTION SET QuestionID=?,ParentQuestionID=? WHERE InteractionID=?',(key,row['QuestionID'],row['InteractionID']))
        previous[row['SessionID']] = row


def upgrade_previous_v3(path):
    """Import the earlier local v3 variant without throwing away extra fields.

    Build and verify a separate file, then replace the stopped database. Unknown
    legacy columns are archived per row, rather than silently discarded.
    """
    import os
    import tempfile
    from .database import connect, initialize_database
    path = Path(path).resolve()
    backups = path.parent / 'database-backups'
    backups.mkdir(exist_ok=True)
    backup = backups / ('before-erd-v4-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as dest:
        source.backup(dest)
    with tempfile.TemporaryDirectory(prefix='erd-v4-',dir=path.parent) as folder:
        staged = Path(folder) / 'assessment.sqlite3'
        initialize_database(staged)
        with closing(sqlite3.connect(backup)) as source, connect(staged) as target:
            source.row_factory = sqlite3.Row
            target.execute('PRAGMA foreign_keys=OFF')
            target.execute('CREATE TABLE LEGACY_ERD_FIELDS(TableName TEXT,RowID TEXT,FieldsJSON TEXT NOT NULL,PRIMARY KEY(TableName,RowID))')
            target.executemany('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)',
                source.execute('SELECT version,applied_at FROM schema_migrations').fetchall())
            order = ('USER','AUTH_SESSION','DEPARTMENT','USER_DEPART','COURSE','USER_COURSE',
                'STUDENT','INSTRUCTOR','SECTION','STUDENT_SEC','COURSE_DOC','DOC_CHUNKS','EXAM',
                'EXAM_DOC','EXAM_PUBLICATION','QUEST_BANK','QUEST_ESS','SESSION','INTERACTION',
                'RECORDING','CLIP_RESP','CLIP_TRANS','analytics_runs','analytics_model_calls')
            known = set(order) | {'schema_migrations','sqlite_sequence'}
            source_tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            unknown_tables = source_tables - known
            if unknown_tables:
                raise ValueError(f'Unmapped legacy v3 tables: {sorted(unknown_tables)}; original retained')
            for table in order:
                if table not in source_tables:
                    continue
                if table.startswith('analytics_'):
                    target.execute(source.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0])
                if table == 'QUEST_BANK':
                    target.execute('DELETE FROM QUEST_BANK')
                target_columns = {r[1] for r in target.execute(f'PRAGMA table_info("{table}")')}
                primary = [r[1] for r in target.execute(f'PRAGMA table_info("{table}")') if r[5]]
                rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
                for row in rows:
                    old = dict(row)
                    data = {k:v for k,v in old.items() if k in target_columns}
                    if table == 'SESSION':
                        data['UserID'] = old.get('StudentID')
                    if table == 'QUEST_ESS':
                        bank = source.execute('SELECT ExamID FROM QUEST_BANK WHERE BankID=?',(old['BankID'],)).fetchone()
                        data['ExamID'] = bank[0] if bank else None
                    if table == 'INTERACTION':
                        data['ActualQuestionTxt'] = old['ActualQuestion']
                        data['StartTime'] = old.get('StartTime') or ''
                        data['EndTime'] = old.get('EndTime')
                    if table == 'RECORDING':
                        data['RecordingStatus'] = 'complete' if old.get('RecordingPath') else 'unavailable_legacy'
                    if table == 'CLIP_RESP':
                        data['RespClipID'] = old['RespClip']
                        if not old['RecordingID']:
                            session_id = target.execute('SELECT SessionID FROM INTERACTION WHERE InteractionID=?',(old['InteractionID'],)).fetchone()[0]
                            target.execute('''INSERT OR IGNORE INTO RECORDING(RecordingID,SessionID,RecordingStatus)
                                VALUES(?,?,'unavailable_legacy')''',(session_id,session_id))
                            data['RecordingID'] = session_id
                        # The older variant used offsets, not UTC timestamps.
                        data['StartTime'] = data['EndTime'] = None
                        data['EndTime'] = old.get('AnsweredAt')
                        rec = source.execute('SELECT StartTime FROM RECORDING WHERE RecordingID=?',(old['RecordingID'],)).fetchone()
                        if rec and rec[0]:
                            from datetime import timedelta
                            try:
                                start = datetime.fromisoformat(rec[0])
                                for name in ('StartTime','EndTime'):
                                    if old.get(name) is not None:
                                        data[name] = (start + timedelta(seconds=float(old[name]))).isoformat()
                            except (ValueError,TypeError):
                                pass  # Original values remain in LEGACY_ERD_FIELDS.
                    keys = ','.join(f'"{k}"' for k in data)
                    update = ','.join(f'"{k}"=excluded."{k}"' for k in data if k not in primary)
                    conflict = ','.join(f'"{k}"' for k in primary)
                    statement = f'INSERT INTO "{table}"({keys}) VALUES('+','.join('?' for _ in data)+')'
                    statement += f' ON CONFLICT({conflict}) DO UPDATE SET {update}' if update else f' ON CONFLICT({conflict}) DO NOTHING'
                    target.execute(statement,tuple(data.values()))
                    extras = {k:v for k,v in old.items() if k not in target_columns}
                    if table == 'CLIP_RESP':
                        extras.update(StartTime=old['StartTime'],EndTime=old['EndTime'])
                    if table == 'INTERACTION':
                        extras['AskedAt'] = old['AskedAt']
                    if extras:
                        identity = json.dumps([data[k] for k in primary])
                        target.execute('INSERT INTO LEGACY_ERD_FIELDS VALUES(?,?,?)',(table,identity,json.dumps(extras)))
            for row in source.execute('SELECT * FROM CLIP_TRANS ORDER BY TranscriptID'):
                interaction = target.execute('SELECT InteractionID FROM CLIP_RESP WHERE RespClipID=?',(row['RespClipID'],)).fetchone()
                if interaction:
                    target.execute('UPDATE INTERACTION SET PickedTransID=?,Evaluation=? WHERE InteractionID=? AND PickedTransID IS NULL',
                        (row['TranscriptID'],row['Evaluation'],interaction[0]))
            _legacy_essential_questions(target)
            for row in source.execute('SELECT name,seq FROM sqlite_sequence'):
                target.execute('UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name=?',(row['seq'],row['name']))
            for table in order:
                if table in source_tables:
                    old_count=source.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    new_count=target.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                    if new_count < old_count:
                        raise ValueError(f'Row count mismatch: {table}; original retained')
            if target.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Foreign-key validation failed; original retained')
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Integrity validation failed; original retained')
        with closing(sqlite3.connect(staged)) as c:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            c.execute('PRAGMA journal_mode=DELETE')
        with closing(sqlite3.connect(path)) as c:
            if c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise RuntimeError('Stop services before migration')
            c.execute('PRAGMA journal_mode=DELETE')
        if os.name == 'nt':
            # Preserve Windows ACLs on an existing shared database. SQLite's
            # backup API publishes the verified pages in a destination transaction.
            with closing(sqlite3.connect(staged)) as verified, closing(sqlite3.connect(path)) as destination:
                verified.backup(destination)
        else:
            os.replace(staged,path)
    return backup
