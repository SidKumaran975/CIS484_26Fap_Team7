"""Prepare the shared database before either service starts."""
import os
from datetime import datetime
from pathlib import Path

from .database import ROOT, database_path, initialize_database
from .migration import migrate


def prepare_database():
    destination = database_path()
    if destination.is_file():
        initialize_database(destination)
        return None
    # Legacy variables are migration inputs only. APP_DB_PATH selects the
    # destination for every component, including the faculty authentication.
    defaults = {
        'LEGACY_FACULTY_DB_PATH': os.environ.get('DB_PATH', os.environ.get('FACULTY_DB_PATH', ROOT/'faculty-portal'/'exam_builder.db')),
        'LEGACY_SESSION_DB_PATH': os.environ.get('SESSION_DB_PATH', ROOT/'runtime'/'sessions.sqlite3'),
        'LEGACY_ANALYTICS_DB_PATH': os.environ.get('ANALYTICS_DB_PATH', ROOT/'runtime'/'analytics.sqlite3'),
    }
    sources = [Path(os.environ.get(key,str(value))) for key,value in defaults.items()]
    sources = [p for p in sources if p.is_file() and p.resolve()!=destination]
    if sources:
        backup = destination.parent/'database-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        publication_dir = os.environ.get('FACULTY_EXAMS_DIR')
        return migrate(sources,destination,backup,apply=True,
                       publications_dir=Path(publication_dir) if publication_dir else None)
    initialize_database(destination)
    return None
