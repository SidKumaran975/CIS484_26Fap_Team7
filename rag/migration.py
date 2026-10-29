"""Offline, verified import of legacy stores into a new unified database."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .database import connect, initialize_database, save_avatar, save_publication, SCHEMA_VERSION

ORDER = ('users', 'sessions', 'courses', 'materials', 'chunks', 'professor_media',
         'exams', 'assessment_sessions', 'assessment_turns',
         'analytics_runs', 'analytics_model_calls')


def _readonly(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def migrate(sources: list[Path], destination: Path, backup_dir: Path, *, apply=False, publications_dir: Path | None = None) -> dict:
    """Build in isolation, verify, then publish; source files are never modified.

    An existing destination is refused. Repeating a successful migration is a
    no-op only through normal application schema initialization, not reimport.
    """
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f'Destination already exists: {destination}')
    sources = list(dict.fromkeys(Path(p).resolve() for p in sources))
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(source)
    if not sources:
        raise ValueError('No source databases found; refusing an empty migration')
    if destination in sources:
        raise ValueError('Destination must differ from every source database')
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(backup_dir).resolve()
    if apply:
        backup_dir.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': SCHEMA_VERSION, 'sources': [str(p) for p in sources],
              'destination': str(destination), 'applied': False, 'tables': {}, 'unresolved_links': []}
    with tempfile.TemporaryDirectory(prefix='db-migration-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'assessment.sqlite3'
        snapshots = []
        # Back up through SQLite so committed WAL rows are included. Import only
        # these stable snapshots; a source is never read at two different times.
        for i, source in enumerate(sources):
            snapshot = (backup_dir if apply else Path(temporary)) / f'{i}-{source.name}'
            with closing(_readonly(source)) as reader, closing(sqlite3.connect(snapshot)) as backup:
                reader.backup(backup)
            snapshots.append(snapshot)
        initialize_database(staged)
        readers = [_readonly(p) for p in snapshots]
        try:
            for reader in readers:
                tables = {r[0] for r in reader.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                unknown = {name for name in tables-set(ORDER) if not name.startswith('sqlite_')}
                if unknown:
                    raise ValueError(f'Unmapped legacy tables: {sorted(unknown)}; migration aborted')
            with closing(connect(staged)) as target, target:
                for table in ORDER:
                    total = 0
                    for reader in readers:
                        if not reader.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                            continue
                        if table.startswith('analytics_'):
                            definition = reader.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
                            if not target.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
                                target.execute(definition)
                        for row in reader.execute(f'SELECT * FROM "{table}"'):
                            data = dict(row)
                            if table == 'professor_media':
                                save_avatar(target,data['user_id'],data['version'],data['updated_at'])
                            else:
                                if table in ('assessment_sessions','assessment_turns'):
                                    defaults = {'exam_id':None,'student_id':None,'student_username':None,'student_name':None,
                                                'current_prompt':'','completed_at':None} if table=='assessment_sessions' else {'next_prompt':''}
                                    data = defaults | data
                                columns = {r[1] for r in target.execute(f'PRAGMA table_info("{table}")')}
                                unknown = set(data)-columns
                                if unknown:
                                    raise ValueError(f'Unmapped columns in {table}: {sorted(unknown)}')
                                keys = ','.join(f'"{key}"' for key in data)
                                values = ','.join('?' for _ in data)
                                target.execute(f'INSERT INTO "{table}"({keys}) VALUES({values})',tuple(data.values()))
                                primary = {'users':'id','sessions':'token_hash','courses':'id','materials':'id',
                                           'chunks':'id','exams':'id','assessment_sessions':'id','assessment_turns':'id',
                                           'analytics_runs':'id','analytics_model_calls':'id'}[table]
                                copied = target.execute(f'SELECT * FROM "{table}" WHERE "{primary}"=?',(data[primary],)).fetchone()
                                if copied is None:
                                    raise ValueError(f'Missing copied row in {table}')
                                for key,value in data.items():
                                    actual = copied[key]
                                    if key in {'questions','settings','evaluation_json','retrieved_json','metrics_json','stages_json'} and value is not None:
                                        value,actual = json.loads(value),json.loads(actual)
                                    if actual != value:
                                        raise ValueError(f'Value mismatch in {table}.{key}; migration aborted')
                                if table == 'materials':
                                    target.execute('UPDATE COURSE_DOC SET FileType=? WHERE DocumentID=?',
                                                   (Path(data.get('filename') or '').suffix.lower(),data['id']))
                                if table == 'users' and data['display_name'] != data['username']:
                                    first,_,last = data['display_name'].strip().partition(' ')
                                    target.execute('UPDATE "USER" SET FirstName=?,LastName=? WHERE UserID=?',
                                                   (first or None,last or None,data['id']))
                            total += 1
                    if total:
                        report['tables'][table] = total
                        actual = target.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                        if actual != total:
                            raise ValueError(f'Row-count mismatch in {table}: {total} -> {actual}')
                publication_folders = [Path(publications_dir)] if publications_dir else [p.parent/'exams' for p in sources]
                publication_count = 0
                for row in target.execute("SELECT ExamID FROM EXAM WHERE ExamStatus='published'").fetchall():
                    filename = row[0]+'.json'
                    # IDs are generated by the app; never trust a legacy ID as a path.
                    if Path(filename).name != filename or '/' in filename or '\\' in filename:
                        raise ValueError('Unsafe legacy exam ID')
                    publication = next((folder/filename for folder in publication_folders if (folder/filename).is_file()),None)
                    if publication is None:
                        raise ValueError(f'Missing published snapshot: {filename}; provide --publications-dir')
                    payload = json.loads(publication.read_text(encoding='utf-8'))
                    if payload.get('exam_id') != row[0]:
                        raise ValueError(f'Published exam ID mismatch: {filename}')
                    save_publication(target,payload)
                    publication_count += 1
                    if apply:
                        export_backup = backup_dir/'published-exams'
                        export_backup.mkdir(exist_ok=True)
                        (export_backup/filename).write_text(json.dumps(payload,indent=2),encoding='utf-8')
                report['published_exams'] = publication_count
                unresolved = target.execute('''SELECT SessionID,LegacyCourseID,LegacyExamID,LegacyStudentID FROM "SESSION"
                  WHERE (LegacyCourseID IS NOT NULL AND CourseID IS NULL)
                  OR (LegacyExamID IS NOT NULL AND ExamID IS NULL)
                  OR (LegacyStudentID IS NOT NULL AND UserID IS NULL)''').fetchall()
                report['unresolved_links'] = [dict(r) for r in unresolved]
                violations = target.execute('PRAGMA foreign_key_check').fetchall()
                if violations:
                    raise ValueError(f'Foreign-key violations: {[tuple(r) for r in violations]}')
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite integrity check failed')
            # Close readers before cleanup (Windows does not unlink open files).
        finally:
            for reader in readers:
                reader.close()
        with closing(sqlite3.connect(staged)) as c:
            c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            c.execute('PRAGMA journal_mode=DELETE')
        if apply:
            # A hard link publishes atomically and refuses to overwrite a file
            # another process created while validation was running.
            if os.name == 'nt':
                os.rename(staged, destination)  # Windows refuses existing targets.
            else:
                os.link(staged, destination)
            report['applied'] = True
            (backup_dir/'migration-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
