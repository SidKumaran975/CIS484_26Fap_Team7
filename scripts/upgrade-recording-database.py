"""Offline, backed-up upgrade to the full-session recording ERD."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rag.database import database_path, connect, initialize_database


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=database_path())
    args=parser.parse_args()
    path=args.database.resolve()
    if not path.is_file():
        parser.error(f'Database does not exist: {path}')
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
