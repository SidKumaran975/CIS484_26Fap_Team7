import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag.database import connect, initialize_database
from rag.sessions import SessionStore
from rag.recordings import FullRecordingStore


class RecordingERDTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'exam.db'

    def seed(self, version=6):
        initialize_database(self.path,target_version=version)
        with connect(self.path) as c:
            c.execute("INSERT INTO users VALUES(1,'prof','Professor','faculty','hash','now')")
            c.execute("INSERT INTO users VALUES(2,'student','Student','student','hash','now')")
            c.execute("INSERT INTO courses VALUES('course',1,'CIS','Course','Fall','now')")
            c.execute("INSERT INTO USER_COURSE VALUES(2,'course')")
            c.execute("INSERT INTO exams(id,course_id,professor_id,title,settings,questions,status) VALUES('exam','course',1,'Exam','{}',?,'published')",
                (json.dumps([{'id':'Q1','question':'Explain transactions','key_points':['atomicity']}]),))

    def test_v2_upgrade_preserves_grading_audio_and_profiles(self):
        self.seed(2)
        with connect(self.path) as c:
            c.execute("INSERT INTO AVATAR VALUES('a',1,'face.png','voice.wav','v','now')")
            c.execute("INSERT INTO assessment_sessions(id,exam_id,course_id,student_id,created_at,updated_at) VALUES('s','exam','course',2,'start','start')")
            c.execute("INSERT INTO assessment_turns VALUES('t','s','Q1',1,'Explain transactions','answer',?,'[]','move_on','','finish')",(json.dumps({'feedback':'Good evidence'}),))
            c.execute("INSERT INTO RESP_REC VALUES('t','t','response.webm',2,'audio/webm')")
        initialize_database(self.path)
        initialize_database(self.path)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT AudioFilePath FROM CLIP_RESP').fetchone()[0],'response.webm')
            self.assertEqual(c.execute('SELECT TranscriptText FROM CLIP_TRANS').fetchone()[0],'answer')
            self.assertEqual(c.execute('SELECT PickedTransID FROM INTERACTION').fetchone()[0],'t')
            self.assertEqual(json.loads(c.execute('SELECT Evaluation FROM INTERACTION').fetchone()[0])['feedback'],'Good evidence')
            self.assertEqual(c.execute('SELECT FaceImagePath FROM INSTRUCTOR').fetchone()[0],'face.png')
            self.assertEqual(tuple(c.execute('SELECT StudentID,InstructorID FROM "SESSION"').fetchone()),(2,1))
            self.assertEqual(tuple(c.execute('SELECT StudentID,SectionID FROM STUDENT_SEC').fetchone()),(2,'legacy:course'))
            self.assertEqual(c.execute('SELECT RecordingStatus FROM RECORDING').fetchone()[0],'unavailable_legacy')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(len(list((self.path.parent/'database-backups').glob('before-erd-v4-*'))),1)

    def test_followup_essential_question_and_selected_transcript(self):
        self.seed()
        store=SessionStore(self.path)
        s=store.create('course','exam',student_id=2)
        interaction=store.prepare_interaction(s['id'],'Q1','What happens on failure?','Explain atomicity and rollback.')
        store.timing_event(s['id'],interaction,'question_start','2026-01-01T00:00:01+00:00')
        store.timing_event(s['id'],interaction,'question_end','2026-01-01T00:00:03+00:00')
        store.record_turn_and_update(s['id'],'Q1','What happens on failure?','Rollback',{'feedback':'Correct'},[],'move_on',1,0,True,
            recording={'path':'answer.webm','format':'audio/webm','start_time':'2026-01-01T00:00:04+00:00','end_time':'2026-01-01T00:00:06+00:00','interaction_id':interaction})
        with connect(self.path) as c:
            row=c.execute('SELECT * FROM INTERACTION').fetchone()
            essential=c.execute('SELECT * FROM QUEST_ESS WHERE QuestionID=?',(row['QuestionID'],)).fetchone()
            self.assertEqual(essential['BankID'],'exam')
            self.assertEqual(essential['QuestionText'],'Explain transactions')
            self.assertEqual(row['EssentialQuestion'],'Explain atomicity and rollback.')
            self.assertEqual(c.execute('SELECT count(*) FROM QUEST_ESS').fetchone()[0],1)
            self.assertEqual(row['PickedTransID'],interaction)
            self.assertGreaterEqual(row['EndTime'],'2026-01-01T00:00:06+00:00')
            c.execute('INSERT INTO CLIP_TRANS VALUES(?,?,?)',('alternate',interaction,'Alternate transcript'))
            self.assertEqual(c.execute('SELECT transcript FROM assessment_turns').fetchone()[0],'Rollback')
            c.execute('UPDATE INTERACTION SET PickedTransID=? WHERE InteractionID=?',('alternate',interaction))
            self.assertEqual(c.execute('SELECT transcript FROM assessment_turns').fetchone()[0],'Alternate transcript')
        messages=store.list_for_exams(['exam'])[0]['messages']
        self.assertEqual(messages[0]['essential_question'],'Explain atomicity and rollback.')
        self.assertEqual(messages[1]['evaluation']['feedback'],'Correct')

    def test_cross_interaction_selection_rejected(self):
        self.seed()
        store=SessionStore(self.path)
        ids=[]
        for _ in range(2):
            session=store.create('course','exam')
            ids.append(store.record_turn_and_update(session['id'],'Q1','Question','Answer',{},[],'move_on',1,0,True))
        with self.assertRaises(sqlite3.IntegrityError), connect(self.path) as c:
            c.execute('UPDATE INTERACTION SET PickedTransID=? WHERE InteractionID=?',(ids[0],ids[1]))

    def test_full_recording_retries_missing_chunks_and_interruption(self):
        self.seed()
        sessions=SessionStore(self.path)
        session=sessions.create('course','exam')
        store=FullRecordingStore(self.path,Path(self.temp.name)/'recordings')
        store.start(session['id'],'2026-01-01T00:00:00Z')
        store.chunk(session['id'],1,b'second')
        store.chunk(session['id'],1,b'second')
        with self.assertRaises(ValueError):store.chunk(session['id'],1,b'conflict')
        with self.assertRaises(ValueError):store.finish(session['id'],2,'2026-01-01T00:00:10Z',True)
        store.chunk(session['id'],0,b'first')
        with self.assertRaises(ValueError):store.finish(session['id'],2,'2026-01-01T00:00:10Z')
        store.finish(session['id'],2,'2026-01-01T00:00:10Z',True)
        with connect(self.path) as c:
            row=c.execute('SELECT * FROM RECORDING').fetchone()
            self.assertEqual(row['RecordingStatus'],'interrupted')
            self.assertEqual(Path(row['RecordingPath']).read_bytes(),b'firstsecond')
            self.assertEqual(c.execute('SELECT SessionStatus FROM "SESSION"').fetchone()[0],'interrupted')

    def test_migration_failure_rolls_back_schema(self):
        self.seed(2)
        with connect(self.path) as c:
            c.execute('PRAGMA foreign_keys=OFF')
            c.execute("UPDATE COURSE SET UserID=999")
        with self.assertRaises(ValueError):initialize_database(self.path)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],2)
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='CLIP_RESP'").fetchone())

    def test_earlier_local_v3_is_upgraded_without_losing_fields(self):
        with sqlite3.connect(self.path) as c:
            c.executescript((Path(__file__).parent/'fixtures/schema-local-v3.sql').read_text())
            c.executemany('INSERT INTO schema_migrations(version) VALUES(?)',[(2,),(3,)])
            c.execute("INSERT INTO users VALUES(1,'prof','Professor','faculty','hash','now')")
            c.execute("INSERT INTO users VALUES(2,'student','Student','student','hash','now')")
            c.execute("INSERT INTO courses VALUES('c',1,'CIS','Course','Fall','now')")
            c.execute("INSERT INTO exams(id,course_id,professor_id,title,settings,questions,status) VALUES('e','c',1,'Exam','{}',?,'published')",
                (json.dumps([{'id':'Q1','question':'Explain atomicity'}]),))
            c.execute("INSERT INTO assessment_sessions(id,course_id,exam_id,student_id,created_at,updated_at) VALUES('s','c','e',2,'start','start')")
            c.execute("INSERT INTO assessment_turns VALUES('t','s','Q1',1,'Explain atomicity','all or nothing',?,'[]','move_on','','answer-time')",
                (json.dumps({'feedback':'Good answer'}),))
        c.close()
        initialize_database(self.path)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],6)
            self.assertEqual(c.execute('SELECT transcript FROM assessment_turns').fetchone()[0],'all or nothing')
            self.assertEqual(json.loads(c.execute('SELECT Evaluation FROM INTERACTION').fetchone()[0])['feedback'],'Good answer')
            self.assertTrue(c.execute('SELECT count(*) FROM LEGACY_ERD_FIELDS').fetchone()[0])
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__ == '__main__':
    unittest.main()
