#!/usr/bin/env python3
"""Run while both services are stopped. Defaults to validation without applying."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from rag.migration import migrate

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,action='append',required=True,help='Repeat for faculty, sessions, and analytics databases')
parser.add_argument('--destination',type=Path,required=True)
parser.add_argument('--backup-dir',type=Path,default=ROOT/'local-backups'/('database-'+datetime.now().strftime('%Y%m%d-%H%M%S')))
parser.add_argument('--apply',action='store_true')
parser.add_argument('--publications-dir',type=Path)
args = parser.parse_args()
print(json.dumps(migrate(args.source,args.destination,args.backup_dir,apply=args.apply,publications_dir=args.publications_dir),indent=2))
