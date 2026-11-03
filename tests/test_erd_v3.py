"""Migration preservation and constraints that cross the new ERD entities."""
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from rag.database import connect, initialize_database, read_publication
from rag.sessions import SessionStore


class ERDV3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'assessment.sqlite3'

    def seed_v2(self):
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript((Path(__file__).parents[1]/'rag/schema_v2.sql').read_text(encoding='utf-8'))
            c.execute("INSERT INTO users VALUES(1,'prof','Professor','faculty','same-password-hash','then')")
            c.execute("INSERT INTO users VALUES(2,'student','Student','student','student-hash','then')")
            c.execute("INSERT INTO DEPARTMENT VALUES('d','Department','D')")
            c.execute("INSERT INTO USER_DEPART VALUES(1,'d')")
            c.execute("INSERT INTO courses VALUES('c',1,'CIS','Course','Fall','then')")
            c.execute("INSERT INTO USER_COURSE VALUES(2,'c')")
            c.execute("INSERT INTO AVATAR VALUES('avatar-id',1,'face.png','voice.wav','version','then')")
            questions=json.dumps([{'id':'q','question':'Why?','key_points':['Evidence']}])
            c.execute("INSERT INTO exams(id,course_id,professor_id,title,settings,questions,status) VALUES('e','c',1,'Exam','{}',?,'published')",(questions,))
            c.execute("INSERT INTO EXAM_PUBLICATION VALUES('e','then',?)",(json.dumps({'exam_id':'e','published_at':'then'}),))
            c.execute("INSERT INTO assessment_sessions(id,course_id,exam_id,student_id,created_at,updated_at) VALUES('s','c','e',2,'then','then')")
            c.execute("INSERT INTO assessment_turns VALUES('turn','s','q',1,'Why?','Because.',?, '[]','move_on','','2026-11-03T12:00:00Z')",(json.dumps({'rating':4,'feedback':'Good','evidence':['Because.']}),))
            # Real v2 IDs are not required to equal the response or turn IDs.
            c.execute("UPDATE RESP_TRANS SET TranscriptID='transcript-id'")
            c.execute("UPDATE EVALUATION SET EvaluationID='evaluation-id'")
            c.execute("INSERT INTO RESP_REC VALUES('recording-id','turn','answer.webm',3.5,'audio/webm')")
            c.execute('CREATE TABLE custom_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, note TEXT)')
            c.execute('CREATE INDEX custom_note ON custom_audit(note)')
            c.execute("INSERT INTO custom_audit VALUES(19,'kept')")
            c.execute("UPDATE sqlite_sequence SET seq=50 WHERE name='USER'")
            c.commit()

    def test_v2_upgrade_preserves_all_rows_and_adapters(self):
        self.seed_v2()
        initialize_database(self.path)
        initialize_database(self.path)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],3)
            self.assertEqual(tuple(c.execute('SELECT InstructorID,DepartmentID,FaceImagePath,VoiceSamplePath FROM INSTRUCTOR').fetchone()),(1,'d','face.png','voice.wav'))
            self.assertEqual(tuple(c.execute('SELECT StudentID,SectionID FROM STUDENT_SEC').fetchone()),(2,'legacy-section:c'))
            self.assertEqual(tuple(c.execute('SELECT CourseID,SectionNumber FROM SECTION').fetchone()),('c','legacy'))
            self.assertEqual(tuple(c.execute('SELECT StudentID,InstructorID FROM "SESSION"').fetchone()),(2,1))
            self.assertEqual(tuple(c.execute('SELECT RecordingID,SessionID,RecordingPath FROM RECORDING').fetchone()),('recording-id','s','answer.webm'))
            clip=c.execute('SELECT * FROM CLIP_RESP').fetchone()
            self.assertEqual((clip['RespClip'],clip['InteractionID'],clip['Duration']),('turn','turn',3.5))
            self.assertIsNone(clip['StartTime'])  # Unknown offsets are not invented.
            transcript=c.execute('SELECT * FROM CLIP_TRANS').fetchone()
            self.assertEqual((transcript['TranscriptID'],transcript['EvaluationID']),('transcript-id','evaluation-id'))
            self.assertEqual(json.loads(transcript['Evaluation'])['rating'],4)
            self.assertEqual(c.execute('SELECT note FROM custom_audit').fetchone()[0],'kept')
            self.assertIsNotNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='custom_note'").fetchone())
            self.assertEqual(c.execute("SELECT seq FROM sqlite_sequence WHERE name='USER'").fetchone()[0],50)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(read_publication(c,'e')['exam_id'],'e')
        report=next((self.path.parent/'database-backups').glob('*.report.json'))
        self.assertEqual(json.loads(report.read_text())['verified_tables']['RESP_REC'],1)
        self.assertEqual(len(list((self.path.parent/'database-backups').glob('before-erd-v3-*.sqlite3'))),1)
        turns=SessionStore(self.path).list_for_exams(['e'])[0]
        self.assertEqual(turns['messages'][1]['text'],'Because.')
        self.assertEqual(turns['messages'][1]['recording']['id'],'recording-id')

    def test_conflicting_departments_abort_without_replacing_original(self):
        self.seed_v2()
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("INSERT INTO DEPARTMENT VALUES('other','Other','O')")
            c.execute("INSERT INTO USER_DEPART VALUES(1,'other')")
            c.commit()
        original=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'multiple memberships'):
            initialize_database(self.path)
        self.assertEqual(self.path.read_bytes(),original)

    def test_multiple_clips_transcripts_and_cross_session_rejection(self):
        self.seed_v2()
        initialize_database(self.path)
        store=SessionStore(self.path)
        other=store.create('c','e',student_id=2)
        turn=store.record_turn_and_update(other['id'],'q','Why?','Typed answer',{},[],'move_on',1,0,True)
        with connect(self.path) as c:
            self.assertIsNone(c.execute('SELECT RecordingID FROM CLIP_RESP WHERE RespClip=?',(turn,)).fetchone()[0])
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("UPDATE CLIP_RESP SET RecordingID='recording-id' WHERE RespClip=?",(turn,))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('UPDATE RECORDING SET SessionID=? WHERE RecordingID=\'recording-id\'',(other['id'],))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('UPDATE INTERACTION SET SessionID=? WHERE InteractionID=\'turn\'',(other['id'],))
            c.execute("INSERT INTO CLIP_RESP(RespClip,RecordingID,InteractionID,AudioFilePath,StartTime,EndTime,AnsweredAt) VALUES('clip2','recording-id','turn','clip2.webm',1,2,'2026-11-03T13:00:00Z')")
            c.execute("INSERT INTO CLIP_TRANS(TranscriptID,RespClipID,TranscriptText) VALUES('t2','clip2','first transcription')")
            c.execute("INSERT INTO CLIP_TRANS(TranscriptID,RespClipID,TranscriptText) VALUES('t3','clip2','second transcription')")
            self.assertEqual(c.execute("SELECT count(*) FROM CLIP_RESP WHERE RecordingID='recording-id'").fetchone()[0],2)
            self.assertEqual(c.execute("SELECT count(*) FROM CLIP_TRANS WHERE RespClipID='clip2'").fetchone()[0],2)
            c.execute("UPDATE CLIP_TRANS SET Evaluation='{}',EvaluationID='eval-t2' WHERE TranscriptID='t2'")
            c.execute("UPDATE CLIP_TRANS SET Evaluation='{}',EvaluationID='eval-t3' WHERE TranscriptID='t3'")
            self.assertEqual(c.execute("SELECT count(*) FROM assessment_turns WHERE id='turn'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT transcript FROM assessment_turns WHERE id='turn'").fetchone()[0],'second transcription')
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO STUDENT_SEC VALUES(999,'legacy-section:c')")
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_failed_answer_recording_rolls_back_whole_turn(self):
        self.seed_v2()
        initialize_database(self.path)
        store=SessionStore(self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            store.record_turn_and_update('s','q','q','answer',{},[],'move_on',1,0,True,recording={'path':None})
        self.assertEqual(store.get('s')['completed'],0)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM INTERACTION').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM RECORDING').fetchone()[0],1)

    def test_session_delete_cascades_its_recording_clips_and_transcripts(self):
        self.seed_v2()
        initialize_database(self.path)
        with connect(self.path) as c:
            c.execute('DELETE FROM "SESSION" WHERE SessionID=\'s\'')
            for table in ('INTERACTION','RECORDING','CLIP_RESP','CLIP_TRANS'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__=='__main__':
    unittest.main()
