"""Normalize a Windows-edited SQLite journal before handing the file to WSL.

Run on Windows, with the application and DB Browser closed. SQLite performs
the checkpoint itself; journal files are never manually deleted.
"""
import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


def prepare(path: Path) -> Path | None:
    path = Path(path).resolve()
    if not path.is_file():
        return None
    with path.open('rb') as stream:
        header = stream.read(20)
    if header[:16] != b'SQLite format 3\x00':
        raise RuntimeError('The database file is not a valid SQLite database')
    if header[18:20] == b'\x01\x01':
        return None
    backup_dir = path.parent.parent/'local-backups'/'windows-journal'
    backup_dir.mkdir(parents=True,exist_ok=True)
    backup = backup_dir/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
    try:
        with closing(sqlite3.connect(path,timeout=3)) as db:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise RuntimeError('Database integrity check failed; database left in place')
            with closing(sqlite3.connect(backup)) as snapshot:
                db.backup(snapshot)
            checkpoint = db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
            if checkpoint[0][0]:
                raise RuntimeError('Close DB Browser and stop both services before starting the application')
            if db.execute('PRAGMA journal_mode=DELETE').fetchall() != [('delete',)]:
                raise RuntimeError('Could not prepare the database for WSL')
    except sqlite3.OperationalError as exc:
        raise RuntimeError('Close DB Browser completely and stop both services, then retry Start-Local.cmd. '
                           f'SQLite reported: {exc}') from exc
    return backup


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    args = parser.parse_args()
    try:
        backup = prepare(args.database)
    except RuntimeError as exc:
        parser.exit(1,str(exc)+'\n')
    if backup:
        print(f'Database prepared for WSL; backup: {backup}')
