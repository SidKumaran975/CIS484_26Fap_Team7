"""Backed-up v1 -> v2 upgrade for the revised single-USER ERD.

Run only with both services stopped (the pipeline calls this before launch).
"""
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path


def upgrade_v1(path: Path):
    from .database import initialize_database, connect, SCHEMA_VERSION
    path = Path(path).resolve()
    backups = path.parent/'database-backups'
    backups.mkdir(parents=True,exist_ok=True)
    backup = backups/('before-erd-v2-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
    with closing(sqlite3.connect(path)) as original, closing(sqlite3.connect(backup)) as snapshot:
        original.backup(snapshot)
    renames = {'PROF_DEPART':'USER_DEPART','STUDENT_COURSE':'USER_COURSE'}
    order = ('USER','AUTH_SESSION','DEPARTMENT','PROF_DEPART','COURSE','STUDENT_COURSE','AVATAR',
             'COURSE_DOC','DOC_CHUNKS','EXAM','EXAM_DOC','EXAM_PUBLICATION','QUESTION_BANK','SESSION',
             'INTERACTION','RESPONSE','RESP_TRANS','RESP_REC','EVALUATION','analytics_runs','analytics_model_calls')
    with tempfile.TemporaryDirectory(prefix='erd-v2-',dir=path.parent) as folder:
        staged = Path(folder)/'assessment.sqlite3'
        initialize_database(staged)
        with closing(sqlite3.connect(backup)) as source, connect(staged) as target:
            source.row_factory = sqlite3.Row
            target.execute('PRAGMA foreign_keys=OFF')
            for old_table in order:
                if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(old_table,)).fetchone():
                    continue
                table = renames.get(old_table,old_table)
                if table.startswith('analytics_'):
                    target.execute(source.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0])
                rows = source.execute(f'SELECT * FROM "{old_table}"').fetchall()
                if table == 'AVATAR':
                    rows = source.execute('''SELECT * FROM AVATAR a WHERE AvatarID=(SELECT AvatarID FROM AVATAR b
                        WHERE b.ProfessorID=a.ProfessorID ORDER BY IsCurrent DESC,UpdatedAt DESC,AvatarID DESC LIMIT 1)''').fetchall()
                for row in rows:
                    data = dict(row)
                    if table == 'USER':
                        data.update(Email=None,FirstName=None,LastName=None)
                        for profile in ('PROFESSOR','STUDENT'):
                            identity = source.execute(f'SELECT Email,FirstName,LastName FROM {profile} WHERE UserID=?',(data['UserID'],)).fetchone()
                            if identity:
                                data.update(dict(identity))
                        if not data['FirstName'] and not data['LastName'] and data['DisplayName'] != data['UserName']:
                            first,_,last = data['DisplayName'].strip().partition(' ')
                            data.update(FirstName=first or None,LastName=last or None)
                    if 'ProfessorID' in data:
                        data['UserID'] = data.pop('ProfessorID')
                    if table in ('USER_COURSE','SESSION'):
                        data['UserID'] = data.pop('StudentID')
                    if table == 'COURSE_DOC':
                        data.pop('UserID',None)
                    if table == 'EXAM':
                        data.pop('AvatarID',None)
                    if table == 'AVATAR':
                        data.pop('IsCurrent',None)
                    columns = ','.join(f'"{key}"' for key in data)
                    target.execute(f'INSERT INTO "{table}"({columns}) VALUES('+','.join('?' for _ in data)+')',tuple(data.values()))
                count = target.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                if count != len(rows):
                    raise ValueError(f'Row count mismatch upgrading {table}')
            for row in source.execute('SELECT name,seq FROM sqlite_sequence'):
                if target.execute('SELECT 1 FROM sqlite_sequence WHERE name=?',(row[0],)).fetchone():
                    target.execute('UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name=?',(row[1],row[0]))
            if target.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Foreign-key check failed; original database retained')
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Integrity check failed; original database retained')
        with closing(sqlite3.connect(staged)) as c:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            c.execute('PRAGMA journal_mode=DELETE')
        with closing(sqlite3.connect(path,timeout=30)) as c:
            if c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise RuntimeError('Stop both services before upgrading the database')
            c.execute('PRAGMA journal_mode=DELETE')
        os.replace(staged,path)
    return backup
