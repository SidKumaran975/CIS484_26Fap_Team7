"""Page 10 alignment preserves existing data and real application routes."""
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag.database import connect, initialize_database, read_publication, save_publication


class Page10MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'exam.db'
        initialize_database(self.path, target_version=4)
        with connect(self.path) as c:
            c.execute("INSERT INTO users VALUES(1,'prof','Professor','faculty','hash','now')")
            c.execute("INSERT INTO users VALUES(2,'student','Student','student','hash','now')")
            c.execute("INSERT INTO courses VALUES('c',1,'CIS','Course','Fall','now')")
            c.execute("INSERT INTO USER_COURSE VALUES(2,'c')")
            c.execute("INSERT INTO exams(id,course_id,professor_id,title,settings,questions,status) VALUES('e','c',1,'Exam','{}',?,'published')",
                      (json.dumps([{'id': 'Q1', 'question': 'Explain atomicity'}]),))
            c.execute("INSERT INTO assessment_sessions(id,exam_id,course_id,student_id,created_at,updated_at) VALUES('s','e','c',2,'start','start')")
            c.execute("INSERT INTO assessment_turns VALUES('t','s','Q1',1,'Explain atomicity','all or nothing',?,'[]','move_on','','finish')",
                      (json.dumps({'feedback': 'Good answer'}),))
            c.execute("INSERT INTO RESP_REC VALUES('t','t','answer.webm',2,'audio/webm')")
            save_publication(c, {'exam_id': 'e', 'published_at': 'now', 'questions': [{'question': 'Explain atomicity'}]})

    @staticmethod
    def contents(c):
        return {r[0]: [dict(row) for row in c.execute('SELECT * FROM "' + r[0] + '"')]
                for r in c.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_migrations'").fetchall()}

    def test_preserves_every_row_and_column_with_renamed_clip_keys(self):
        with connect(self.path) as c:
            before = self.contents(c)
        for row in before['CLIP_RESP']:
            row['RespClip'] = row.pop('RespClipID')
            row['Recording'] = row.pop('RecordingID')
        initialize_database(self.path, target_version=5)
        initialize_database(self.path, target_version=5)
        with connect(self.path) as c:
            self.assertEqual(self.contents(c), before)
            self.assertEqual(c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0], 5)
            self.assertEqual(c.execute('SELECT transcript FROM assessment_turns').fetchone()[0], 'all or nothing')
            self.assertEqual(read_publication(c, 'e')['questions'][0]['question'], 'Explain atomicity')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
            clip_fk = {(r['from'], r['table'], r['to']) for r in c.execute('PRAGMA foreign_key_list(CLIP_TRANS)')}
            self.assertIn(('RespClipID', 'CLIP_RESP', None), clip_fk)
            self.assertEqual([r['name'] for r in c.execute('PRAGMA table_info(CLIP_RESP)') if r['pk']], ['RespClip'])
            self.assertIn(('Recording', 'RECORDING', None),
                          {(r['from'], r['table'], r['to']) for r in c.execute('PRAGMA foreign_key_list(CLIP_RESP)')})
        backups = list((self.path.parent / 'database-backups').glob('before-erd-v5-*'))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as c:
            self.assertEqual(c.execute('SELECT RespClipID,RecordingID FROM CLIP_RESP').fetchone(), ('t', 's'))
            self.assertEqual(c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0], 4)

    def test_multiple_banks_and_default_bank_routing(self):
        initialize_database(self.path, target_version=5)
        with connect(self.path) as c:
            c.execute("INSERT INTO QUEST_BANK VALUES('another-bank','e','source')")
            c.execute("INSERT INTO QUEST_ESS(QuestionID,ExamID,ExternalQuestionID,QuestionText,SequenceNumber,QuestionData) VALUES('e:Q2','e','Q2','Second',2,'{}')")
            self.assertEqual(c.execute("SELECT count(*) FROM QUEST_BANK WHERE ExamID='e'").fetchone()[0], 2)
            self.assertEqual(c.execute("SELECT BankID FROM QUEST_ESS WHERE QuestionID='e:Q2'").fetchone()[0], 'e')
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO CLIP_TRANS VALUES('orphan','missing','text')")

    def test_invalid_foreign_key_rolls_back_all_schema_changes(self):
        with connect(self.path) as c:
            c.execute('PRAGMA foreign_keys=OFF')
            c.execute("UPDATE QUEST_BANK SET ExamID='missing'")
        with self.assertRaisesRegex(ValueError, 'foreign-key validation failed'):
            initialize_database(self.path, target_version=5)
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0], 4)
            self.assertEqual(c.execute('SELECT RespClipID,RecordingID FROM CLIP_RESP').fetchone()[0], 't')
            self.assertIsNotNone(c.execute("SELECT 1 FROM sqlite_schema WHERE name='selected_transcript_update'").fetchone())
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_schema WHERE name='QUEST_BANK_v5'").fetchone())


if __name__ == '__main__':
    unittest.main()
