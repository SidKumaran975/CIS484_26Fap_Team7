"""Offline, backed-up upgrade to the full-session recording ERD."""
import argparse
import json
import os
import socket
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rag.database import database_path, connect, initialize_database


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=database_path())
    parser.add_argument('--check-only',action='store_true',help='Upgrade a temporary copy and leave the source database unchanged')
    args=parser.parse_args()
    path=args.database.resolve()
    if not path.is_file():
        parser.error(f'Database does not exist: {path}')
    if args.check_only:
        with tempfile.TemporaryDirectory(prefix='erd-preflight-') as folder:
            staged=Path(folder)/'assessment.sqlite3'
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(staged)) as target:
                source.backup(target)
            initialize_database(staged)
            with connect(staged) as c:
                print(json.dumps({'source':str(path),'check_only':True,
                    'schema_version':c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],
                    'integrity':c.execute('PRAGMA integrity_check').fetchone()[0],
                    'foreign_key_errors':len(c.execute('PRAGMA foreign_key_check').fetchall())},indent=2))
        return
    for port in {int(os.environ.get('STT_PORT','8000')),int(os.environ.get('PORT','8001'))}:
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1',port))
            except OSError:
                parser.error(f'Stop both application services before migration (port {port} is in use)')
    initialize_database(path)
    with connect(path) as c:
        errors=c.execute('PRAGMA foreign_key_check').fetchall()
        integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
        if errors or integrity != 'ok':
            raise RuntimeError('Database verification failed')
        report={'database':str(path),'schema_version':c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],
            'integrity':integrity,'foreign_key_errors':len(errors),
            'rows':{t:c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in
                ('USER','STUDENT','INSTRUCTOR','COURSE','SECTION','EXAM','SESSION','INTERACTION','RECORDING','CLIP_RESP','CLIP_TRANS')}}
    report_path=path.parent/'recording-erd-upgrade-report.json'
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    print('Backups:',path.parent/'database-backups')


if __name__=='__main__':
    main()
