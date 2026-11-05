"""Backed-up alignment with ERD (Page 1) (10).png.

Keep operational metadata rather than deleting data required by the application.
"""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .database import connect


def upgrade_v4(path: Path):
    path = Path(path)
    with connect(path) as probe:
        version = probe.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
        if version >= 5:
            return
        if version != 4:
            raise ValueError('ERD page 10 migration requires schema version 4')
    backups = path.parent / 'database-backups'
    backups.mkdir(exist_ok=True)
    backup = backups / ('before-erd-v5-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as dest:
        source.backup(dest)
    with connect(path) as c:
        c.execute('PRAGMA foreign_keys=OFF')
        c.execute('PRAGMA legacy_alter_table=ON')
        c.execute('BEGIN IMMEDIATE')
        counts = {r[0]: c.execute('SELECT count(*) FROM "' + r[0].replace('"', '""') + '"').fetchone()[0]
                  for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
        # Shared-column joins must become explicit: the ERD names the PK
        # RespClip, while the transcript's FK remains RespClipID.
        c.execute('DROP TRIGGER selected_transcript_insert')
        c.execute('DROP TRIGGER selected_transcript_update')
        c.execute('PRAGMA legacy_alter_table=OFF')
        c.execute('ALTER TABLE CLIP_RESP RENAME COLUMN RespClipID TO RespClip')
        c.execute('ALTER TABLE CLIP_RESP RENAME COLUMN RecordingID TO Recording')
        # An exam can have multiple question banks in the diagram. Preserve the
        # app's default bank without imposing a one-bank-per-exam constraint.
        c.execute('PRAGMA legacy_alter_table=ON')
        c.execute('''CREATE TABLE QUEST_BANK_v5 (
            BankID TEXT PRIMARY KEY, ExamID TEXT NOT NULL REFERENCES EXAM ON DELETE CASCADE, DocSource TEXT)''')
        c.execute('INSERT INTO QUEST_BANK_v5 SELECT BankID,ExamID,DocSource FROM QUEST_BANK')
        c.execute('DROP TABLE QUEST_BANK')
        c.execute('ALTER TABLE QUEST_BANK_v5 RENAME TO QUEST_BANK')
        c.execute('CREATE INDEX quest_bank_exam ON QUEST_BANK(ExamID)')
        c.execute('DROP TRIGGER essential_bank_insert')
        c.execute('''CREATE TRIGGER essential_bank_insert AFTER INSERT ON QUEST_ESS
            WHEN NEW.BankID IS NULL AND NEW.ExamID IS NOT NULL BEGIN
            UPDATE QUEST_ESS SET BankID=(SELECT BankID FROM QUEST_BANK WHERE ExamID=NEW.ExamID
                ORDER BY (BankID=NEW.ExamID) DESC,BankID LIMIT 1)
            WHERE QuestionID=NEW.QuestionID; END''')
        for event, suffix in (('INSERT', 'insert'), ('UPDATE OF PickedTransID', 'update')):
            c.execute(f'''CREATE TRIGGER selected_transcript_{suffix} BEFORE {event} ON INTERACTION
                WHEN NEW.PickedTransID IS NOT NULL BEGIN
                SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM CLIP_TRANS t
                    JOIN CLIP_RESP c ON c.RespClip=t.RespClipID
                    WHERE t.TranscriptID=NEW.PickedTransID AND c.InteractionID=NEW.InteractionID)
                THEN RAISE(ABORT,'Selected transcript belongs to a different interaction') END; END''')
        for table, count in counts.items():
            if c.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] != count:
                raise ValueError(f'Row count changed for {table}; migration rolled back')
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('ERD page 10 foreign-key validation failed; migration rolled back')
        if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('ERD page 10 integrity validation failed; migration rolled back')
        # Compile every compatibility view, including those updated by SQLite's
        # column rename, before committing any changes.
        for row in c.execute("SELECT name FROM sqlite_schema WHERE type='view'").fetchall():
            c.execute('SELECT * FROM "' + row[0].replace('"', '""') + '" LIMIT 0')
        c.execute('INSERT INTO schema_migrations(version) VALUES(5)')
    return backup
