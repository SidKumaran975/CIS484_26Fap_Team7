"""Durable, retryable full-session recording segments."""
import hashlib
import shutil
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .database import connect


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    if parsed > datetime.now(timezone.utc).replace(microsecond=999999):
        # Permit small browser/server clock differences.
        if (parsed - datetime.now(timezone.utc)).total_seconds() > 30:
            raise ValueError('Timestamp is in the future')
    return parsed.astimezone(timezone.utc).isoformat()


class FullRecordingStore:
    def __init__(self, database, root):
        self.database, self.root = database, Path(root)

    def start(self, session_id, start_time):
        start_time = timestamp(start_time)
        with connect(self.database) as c:
            row = c.execute('SELECT * FROM RECORDING WHERE RecordingID=?',(session_id,)).fetchone()
            if row and row['RecordingStatus'] not in ('pending','recording'):
                raise ValueError('Recording has already ended')
            c.execute('''INSERT INTO RECORDING(RecordingID,SessionID,StartTime,RecordingStatus,FileFormat)
                VALUES(?,?,?,'recording','video/webm') ON CONFLICT(RecordingID) DO UPDATE SET
                StartTime=excluded.StartTime,RecordingStatus='recording',FileFormat='video/webm' ''',(session_id,session_id,start_time))
            c.execute('UPDATE "SESSION" SET StartTime=? WHERE SessionID=?',(start_time,session_id))

    def chunk(self, session_id, index, payload):
        if not 0 <= index < 100000 or not payload:
            raise ValueError('Invalid recording segment')
        with connect(self.database) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT RecordingStatus FROM RECORDING WHERE RecordingID=?',(session_id,)).fetchone()
            if not row or row[0] != 'recording':
                raise ValueError('Recording is not active')
            folder = self.root / session_id
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'{index:06d}.part'
            if path.exists():
                if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(payload).digest():
                    raise ValueError('Conflicting recording segment')
                return
            temporary = folder / (str(uuid.uuid4()) + '.upload')
            try:
                temporary.write_bytes(payload)
                os.replace(temporary,path)
            finally:
                temporary.unlink(missing_ok=True)

    def finish(self, session_id, count, end_time, interrupted=False):
        end_time = timestamp(end_time)
        with connect(self.database) as c:
            row = c.execute('SELECT * FROM RECORDING WHERE RecordingID=?',(session_id,)).fetchone()
            session = c.execute('SELECT SessionStatus FROM "SESSION" WHERE SessionID=?',(session_id,)).fetchone()
            if not row or end_time < row['StartTime']:
                raise ValueError('Invalid recording timeline')
            if row['RecordingStatus'] in ('complete','interrupted'):
                return
            if not interrupted and session[0] != 'completed':
                raise ValueError('The AI has not concluded this exam')
            if not 0 < count < 100000:
                raise ValueError('No recording segments received')
            folder = self.root / session_id
            segments = [folder / f'{i:06d}.part' for i in range(count)]
            if any(not p.is_file() for p in segments):
                raise ValueError('Recording segments are missing; retry upload')
            path = folder / 'full-session.webm'
            with path.open('wb') as out:
                for segment in segments:
                    with segment.open('rb') as source:
                        shutil.copyfileobj(source,out)
            c.execute('UPDATE RECORDING SET EndTime=?,RecordingPath=?,RecordingStatus=? WHERE RecordingID=?',
                (end_time,str(path.resolve()),'interrupted' if interrupted else 'complete',session_id))
            if interrupted:
                c.execute('UPDATE "SESSION" SET EndTime=?,SessionStatus=\'interrupted\' WHERE SessionID=?',(end_time,session_id))
