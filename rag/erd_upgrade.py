"""Verified, backed-up conversion from v2 to the section/recording ERD.

Run with both services stopped. The original file is replaced only after all
old logical rows and foreign keys have been verified in a staged database.
"""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import json
import os
import sqlite3
import tempfile


def _insert(c, table, data):
    columns = ','.join('"'+key+'"' for key in data)
    c.execute(f'INSERT INTO "{table}"({columns}) VALUES('+','.join('?' for _ in data)+')', tuple(data.values()))


def _rows(c, table):
    return [dict(row) for row in c.execute(f'SELECT * FROM "{table}"')]


def _verify_rows(source, target, table, rename=None):
    """Compare every original value, including password hashes and JSON bytes."""
    columns = [r[1] for r in source.execute(f'PRAGMA table_info("{table}")')]
    selection = ','.join('"'+(rename or {}).get(key,key)+'"' for key in columns)
    before = sorted((tuple(row[key] for key in columns) for row in _rows(source, table)),key=repr)
    after = sorted((tuple(row) for row in target.execute(f'SELECT {selection} FROM "{table}"')),key=repr)
    if before != after:
        raise ValueError(f'Row/value mismatch upgrading {table}; original retained')
    return len(before)


def upgrade_v2(path: Path):
    from .database import initialize_database, connect
    path = Path(path).resolve()
    backups = path.parent/'database-backups'
    backups.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = backups/f'before-erd-v3-{stamp}.sqlite3'
    report = {'schema_version':3,'database':str(path),'backup':str(backup),'verified_tables':{}}
    with closing(sqlite3.connect(path,timeout=30)) as original, closing(sqlite3.connect(backup)) as snapshot:
        original.backup(snapshot)
    with tempfile.TemporaryDirectory(prefix='erd-v3-',dir=path.parent) as folder:
        staged = Path(folder)/'assessment.sqlite3'
        initialize_database(staged)
        with closing(sqlite3.connect(backup)) as source, connect(staged) as target:
            source.row_factory = sqlite3.Row
            memberships = _rows(source,'USER_DEPART')
            counts = {}
            for row in memberships:
                counts[row['UserID']] = counts.get(row['UserID'],0)+1
            if any(n>1 for n in counts.values()):
                raise ValueError('ERD permits one department per instructor; multiple memberships found. Original retained.')
            for table in ('USER','AUTH_SESSION','DEPARTMENT'):
                for row in _rows(source,table):
                    _insert(target,table,row)
            # Preserve valid historical links even when an old account has both
            # taught a course and taken a practice assessment.
            for table, column in (('COURSE','UserID'),('EXAM','UserID'),('AVATAR','UserID'),('USER_DEPART','UserID')):
                for row in source.execute(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'):
                    target.execute('INSERT OR IGNORE INTO INSTRUCTOR(InstructorID) VALUES(?)',(row[0],))
            for row in source.execute('SELECT DISTINCT UserID FROM "SESSION" WHERE UserID IS NOT NULL UNION SELECT UserID FROM USER_COURSE'):
                target.execute('INSERT OR IGNORE INTO STUDENT(StudentID) VALUES(?)',(row[0],))
            for row in memberships:
                target.execute('UPDATE INSTRUCTOR SET DepartmentID=? WHERE InstructorID=?',(row['DepartmentID'],row['UserID']))
            for row in _rows(source,'AVATAR'):
                target.execute('''UPDATE INSTRUCTOR SET AvatarID=?,FaceImagePath=?,VoiceSamplePath=?,MediaVersion=?,UpdatedAt=?
                                  WHERE InstructorID=?''',
                               (row['AvatarID'],row['FaceImagePath'],row['VoiceSamplePath'],row['MediaVersion'],row['UpdatedAt'],row['UserID']))
            for table in ('COURSE','COURSE_DOC','DOC_CHUNKS','EXAM','EXAM_DOC','EXAM_PUBLICATION'):
                for row in _rows(source,table):
                    _insert(target,table,row)
            # No section numbers existed in v2. Only existing enrollments receive
            # an explicitly labeled legacy section; real section numbers remain
            # for faculty to supply rather than being invented by migration.
            for row in _rows(source,'USER_COURSE'):
                target.execute('INSERT INTO USER_COURSE(UserID,CourseID) VALUES(?,?)',(row['UserID'],row['CourseID']))
            for row in _rows(source,'QUESTION_BANK'):
                exam = row.pop('ExamID')
                bank = 'bank:'+exam if exam is not None else 'legacy-bank:'+row['QuestionID']
                target.execute('INSERT OR IGNORE INTO QUEST_BANK(BankID,ExamID) VALUES(?,?)',(bank,exam))
                row['BankID'] = bank
                _insert(target,'QUEST_ESS',row)
            for row in _rows(source,'SESSION'):
                row['StudentID'] = row.pop('UserID')
                course = target.execute('SELECT UserID FROM COURSE WHERE CourseID=coalesce(?,(SELECT CourseID FROM EXAM WHERE ExamID=?))',
                                        (row['CourseID'],row['ExamID'])).fetchone()
                row['InstructorID'] = course[0] if course else None
                _insert(target,'SESSION',row)
            for row in _rows(source,'INTERACTION'):
                _insert(target,'INTERACTION',row)
            for row in _rows(source,'RESPONSE'):
                row['RespClip'] = row.pop('ResponseID')
                _insert(target,'CLIP_RESP',row)
            for row in _rows(source,'RESP_TRANS'):
                row['RespClipID'] = row.pop('ResponseID')
                _insert(target,'CLIP_TRANS',row)
            for row in _rows(source,'EVALUATION'):
                result = target.execute('''UPDATE CLIP_TRANS SET EvaluationID=?,Rating=?,Feedback=?,Evaluation=? WHERE RespClipID=?''',
                                        (row['EvaluationID'],row['Rating'],row['Feedback'],row['EvaluationJSON'],row['ResponseID']))
                if result.rowcount != 1:
                    raise ValueError('Evaluation without exactly one transcript; original retained')
            for row in _rows(source,'RESP_REC'):
                interaction = target.execute('''SELECT i.SessionID FROM CLIP_RESP c JOIN INTERACTION i ON i.InteractionID=c.InteractionID
                                               WHERE c.RespClip=?''',(row['ResponseID'],)).fetchone()
                _insert(target,'RECORDING',{'RecordingID':row['RecordingID'],'SessionID':interaction[0], 'RecordingPath':row['AudioFilePath']})
                target.execute('''UPDATE CLIP_RESP SET RecordingID=?,LegacyRecordingID=?,AudioFilePath=?,Duration=?,FileFormat=? WHERE RespClip=?''',
                               (row['RecordingID'],row['RecordingID'],row['AudioFilePath'],row['Duration'],row['FileFormat'],row['ResponseID']))
            # Preserve operational/extension tables as well as their indexes and
            # triggers; an unrecognized table is never silently discarded.
            canonical = {'schema_migrations','USER','AUTH_SESSION','DEPARTMENT','USER_DEPART','COURSE','USER_COURSE','AVATAR',
                         'COURSE_DOC','DOC_CHUNKS','EXAM','EXAM_DOC','EXAM_PUBLICATION','QUESTION_BANK','SESSION',
                         'INTERACTION','RESPONSE','RESP_TRANS','RESP_REC','EVALUATION','sqlite_sequence'}
            extensions = [(r['name'],r['sql']) for r in source.execute("SELECT name,sql FROM sqlite_master WHERE type='table'") if r['name'] not in canonical]
            for table,sql in extensions:
                target.execute(sql)
                for row in _rows(source,table):
                    _insert(target,table,row)
            for table,_ in extensions:
                for row in source.execute("SELECT sql FROM sqlite_master WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL",(table,)):
                    target.execute(row[0])
            for row in source.execute('SELECT name,seq FROM sqlite_sequence'):
                if target.execute('SELECT 1 FROM sqlite_sequence WHERE name=?',(row[0],)).fetchone():
                    target.execute('UPDATE sqlite_sequence SET seq=max(seq,?) WHERE name=?',(row[1],row[0]))
            for row in _rows(source,'schema_migrations'):
                _insert(target,'schema_migrations',row)
            for row in source.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT IN ('sqlite_sequence','schema_migrations')"):
                table = row[0]
                report['verified_tables'][table] = _verify_rows(source,target,table,{'UserID':'StudentID'} if table=='SESSION' else None)
            if target.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Foreign-key check failed; original retained')
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Integrity check failed; original retained')
        with closing(sqlite3.connect(staged)) as c:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            c.execute('PRAGMA journal_mode=DELETE')
        # Detect writers since the snapshot. Both services must remain stopped
        # until the replacement is complete, as with the preceding v1 upgrade.
        with closing(sqlite3.connect(path,timeout=30)) as current, closing(sqlite3.connect(backup)) as before:
            current.row_factory = before.row_factory = sqlite3.Row
            current.execute('BEGIN EXCLUSIVE')
            for table in report['verified_tables']:
                _verify_rows(before,current,table)
            current.rollback()
            if current.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise RuntimeError('Stop both services before upgrading the database')
            current.execute('PRAGMA journal_mode=DELETE')
        os.replace(staged,path)
    report['integrity_check'] = 'ok'
    report['foreign_key_violations'] = []
    backup.with_suffix('.report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return backup
