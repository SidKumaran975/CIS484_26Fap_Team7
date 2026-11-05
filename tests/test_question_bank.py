import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag.database import connect, initialize_database
from rag.sessions import SessionStore


class QuestionBankTests(unittest.TestCase):
    def test_upgrade_removes_turn_copies_and_keeps_history(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'assessment.db'
            initialize_database(path, target_version=5)
            with connect(path) as c:
                c.execute("INSERT INTO users VALUES(1,'prof','Professor','faculty','hash','now')")
                c.execute("INSERT INTO courses VALUES('c',1,'CIS','Course','Fall','now')")
                c.execute("INSERT INTO exams(id,course_id,title,settings,questions,status) VALUES('e','c','Exam','{}',?,'published')",
                          (json.dumps([{'id':'Q1','question':'Explain transactions'}]),))
                c.execute("INSERT INTO assessment_sessions(id,exam_id,course_id,created_at,updated_at) VALUES('s','e','c','now','now')")
                c.execute("INSERT INTO assessment_turns VALUES('t','s','Q1',1,'What happens on failure?','Rollback','{}','[]','move_on','','now')")
                c.execute("INSERT INTO QUEST_ESS(QuestionID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive) VALUES('followup:t','Q1','Explain rollback','follow_up',0,'{}',0)")
                c.execute("UPDATE INTERACTION SET QuestionID='followup:t',ParentQuestionID='e:Q1'")
            initialize_database(path)
            initialize_database(path)
            with connect(path) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM QUEST_ESS').fetchone()[0], 1)
                turn = c.execute('SELECT * FROM INTERACTION').fetchone()
                self.assertEqual(turn['QuestionID'], 'e:Q1')
                self.assertEqual(turn['EssentialQuestion'], 'Explain rollback')
                self.assertEqual(c.execute('SELECT transcript FROM assessment_turns').fetchone()[0], 'Rollback')
                self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(), [])
            store = SessionStore(path)
            session = store.create('c','e')
            for prompt, essential in [('Explain transactions', None), ('What happens on failure?', 'Explain rollback')]:
                interaction = store.prepare_interaction(session['id'], 'Q1', prompt, essential)
                store.record_turn_and_update(session['id'], 'Q1', prompt, 'Answer', {}, [], 'probe', 0, 1, False)
                with connect(path) as c:
                    self.assertEqual(c.execute('SELECT count(*) FROM QUEST_ESS').fetchone()[0], 1)
                    self.assertEqual(c.execute('SELECT QuestionID FROM INTERACTION WHERE InteractionID=?', (interaction,)).fetchone()[0], 'e:Q1')
            self.assertEqual(len(list((path.parent/'database-backups').glob('before-questions-v6-*'))), 1)

    def test_standalone_turn_does_not_invent_bank_question(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'assessment.db'
            store = SessionStore(path)
            session = store.create('legacy-course')
            store.prepare_interaction(session['id'], 'Q1', 'Explain transactions')
            store.record_turn_and_update(session['id'], 'Q1', 'Explain transactions', 'Answer', {}, [], 'move_on', 1, 0, True)
            with connect(path) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM QUEST_ESS').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT question_id FROM assessment_turns').fetchone()[0], 'Q1')


if __name__ == '__main__':
    unittest.main()
