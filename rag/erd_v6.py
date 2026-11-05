"""Keep professor questions in the bank and per-turn questions in INTERACTION."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .database import connect


TURN_VIEW = '''CREATE VIEW assessment_turns AS SELECT
 i.InteractionID id,i.SessionID session_id,i.ExternalQuestionID question_id,
 i.SequenceNumber turn_number,i.ActualQuestionTxt prompt,t.TranscriptText transcript,
 i.Evaluation evaluation_json,i.RetrievedJSON retrieved_json,i.NextAction action,
 i.NextPrompt next_prompt,c.EndTime created_at
 FROM INTERACTION i JOIN CLIP_RESP c USING(InteractionID)
 JOIN CLIP_TRANS t ON t.TranscriptID=i.PickedTransID'''

TURN_INSERT = '''CREATE TRIGGER compat_assessment_turns_insert
 INSTEAD OF INSERT ON assessment_turns BEGIN
 INSERT INTO INTERACTION(InteractionID,SessionID,QuestionID,ExternalQuestionID,
 EssentialQuestion,ActualQuestionTxt,SequenceNumber,StartTime,NextAction,NextPrompt,
 RetrievedJSON,Evaluation,EndTime)
 VALUES(NEW.id,NEW.session_id,
 (SELECT q.QuestionID FROM QUEST_ESS q JOIN "SESSION" s ON s.ExamID=q.ExamID
 WHERE s.SessionID=NEW.session_id AND q.ExternalQuestionID=NEW.question_id LIMIT 1),
 NEW.question_id,NEW.prompt,NEW.prompt,NEW.turn_number,coalesce(NEW.created_at,''),
 NEW.action,coalesce(NEW.next_prompt,''),NEW.retrieved_json,NEW.evaluation_json,NEW.created_at);
 INSERT OR IGNORE INTO RECORDING(RecordingID,SessionID,StartTime,RecordingStatus)
 SELECT SessionID,SessionID,StartTime,'pending' FROM "SESSION" WHERE SessionID=NEW.session_id;
 INSERT INTO CLIP_RESP(RespClip,InteractionID,Recording,EndTime)
 VALUES(NEW.id,NEW.id,NEW.session_id,NEW.created_at);
 INSERT INTO CLIP_TRANS VALUES(NEW.id,NEW.id,NEW.transcript);
 UPDATE INTERACTION SET PickedTransID=NEW.id WHERE InteractionID=NEW.id;
 END'''


def upgrade_v5(path: Path):
    path = Path(path)
    with connect(path) as c:
        version = c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
        if version >= 6:
            return
        if version != 5:
            raise ValueError('Question storage migration requires schema version 5')
    backups = path.parent / 'database-backups'
    backups.mkdir(exist_ok=True)
    backup = backups / ('before-questions-v6-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    with connect(path) as c:
        c.execute('PRAGMA foreign_keys=OFF')
        c.execute('PRAGMA legacy_alter_table=ON')
        c.execute('BEGIN IMMEDIATE')
        count = c.execute('SELECT count(*) FROM INTERACTION').fetchone()[0]
        c.execute('ALTER TABLE INTERACTION ADD COLUMN EssentialQuestion TEXT')
        c.execute('ALTER TABLE INTERACTION ADD COLUMN ExternalQuestionID TEXT')
        c.execute('''UPDATE INTERACTION SET
            EssentialQuestion=(SELECT QuestionText FROM QUEST_ESS q WHERE q.QuestionID=INTERACTION.QuestionID),
            ExternalQuestionID=(SELECT ExternalQuestionID FROM QUEST_ESS q
                WHERE q.QuestionID=coalesce(INTERACTION.ParentQuestionID,INTERACTION.QuestionID))''')
        # Standalone/legacy sessions may have no surviving professor question.
        # Their external ID and actual prompt remain on the interaction.
        sql = c.execute("SELECT sql FROM sqlite_schema WHERE name='INTERACTION'").fetchone()[0]
        sql = sql.replace('INTERACTION', 'INTERACTION_v6', 1).replace('QuestionID TEXT NOT NULL', 'QuestionID TEXT', 1)
        objects = c.execute("SELECT sql FROM sqlite_schema WHERE tbl_name='INTERACTION' AND type IN ('trigger','index') AND sql IS NOT NULL").fetchall()
        c.execute(sql)
        c.execute('INSERT INTO INTERACTION_v6 SELECT * FROM INTERACTION')
        c.execute('DROP TABLE INTERACTION')
        c.execute('ALTER TABLE INTERACTION_v6 RENAME TO INTERACTION')
        for row in objects:
            c.execute(row[0])
        c.execute('UPDATE INTERACTION SET QuestionID=coalesce(ParentQuestionID,QuestionID)')
        generated = "QuestionSource IN ('follow_up','publication_snapshot','legacy_follow_up','legacy_snapshot') OR (QuestionSource='legacy' AND IsActive=0)"
        for column in ('QuestionID', 'ParentQuestionID'):
            c.execute(f'UPDATE INTERACTION SET {column}=NULL WHERE {column} IN (SELECT QuestionID FROM QUEST_ESS WHERE {generated})')
        c.execute(f'DELETE FROM QUEST_ESS WHERE {generated}')
        c.execute('DROP VIEW assessment_turns')
        c.execute(TURN_VIEW)
        c.execute(TURN_INSERT)
        if c.execute('SELECT count(*) FROM INTERACTION').fetchone()[0] != count:
            raise ValueError('Interaction count changed during question migration')
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Question migration foreign-key validation failed')
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Question migration integrity validation failed')
        for row in c.execute("SELECT name FROM sqlite_schema WHERE type='view'").fetchall():
            c.execute('SELECT * FROM "' + row[0].replace('"', '""') + '" LIMIT 0')
        c.execute('INSERT INTO schema_migrations(version) VALUES(6)')
    return backup
