"""Relational constraints, legacy migration, and storage compatibility."""
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag.database import connect, initialize_database
from rag.migration import migrate
from rag.sessions import SessionStore
from rag.database import read_publication


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root/'unified.db'
        initialize_database(self.path)

    def seed(self):
        with connect(self.path) as c:
            c.execute("INSERT INTO users VALUES(1,'prof','Professor','faculty','unchanged-hash','now')")
            c.execute("INSERT INTO users VALUES(2,'student','Student','student','student-hash','now')")
            c.execute("INSERT INTO courses VALUES('c',1,'CIS','Course','Fall','now')")
            c.execute("INSERT INTO materials(id,filename,course_id) VALUES('doc','notes.txt','c')")
            self.exam(c,'e')

    def test_v1_upgrade_matches_revised_erd_and_keeps_data(self):
        path = self.root/'v1.db'
        with sqlite3.connect(path) as c:
            c.executescript((Path(__file__).parent/'fixtures/schema-v1.sql').read_text())
            c.execute("INSERT INTO users VALUES(1,'prof','Taylor Jones','faculty','same-hash','now')")
            c.execute("INSERT INTO users VALUES(2,'student','Student Name','student','student-hash','now')")
            c.execute("UPDATE PROFESSOR SET FirstName='Taylor',LastName='Jones',Email='taylor@example.test' WHERE UserID=1")
            c.execute("INSERT INTO courses VALUES('c',1,'CIS','Course','Fall','now')")
            c.execute("INSERT INTO STUDENT_COURSE VALUES(2,'c')")
            c.execute("INSERT INTO AVATAR VALUES('old',1,'old.png','old.wav',?, 'yesterday',0)",('a'*64,))
            c.execute("INSERT INTO AVATAR VALUES('current',1,'new.png','new.wav',?, 'today',1)",('b'*64,))
            c.execute("INSERT INTO assessment_sessions(id,course_id,student_id,created_at,updated_at) VALUES('s','c',2,'now','now')")
        c.close()
        initialize_database(path)
        initialize_database(path)
        with connect(path) as c:
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse({'PROFESSOR','STUDENT','PROF_DEPART','STUDENT_COURSE'} & tables)
            self.assertTrue({'USER_COURSE','USER_DEPART'} <= tables)
            self.assertEqual(tuple(c.execute('SELECT FirstName,LastName,Email,PasswordHash FROM "USER" WHERE UserID=1').fetchone()),
                             ('Taylor','Jones','taylor@example.test','same-hash'))
            self.assertEqual(tuple(c.execute('SELECT UserID,FaceImagePath FROM AVATAR').fetchone()),(1,'new.png'))
            self.assertEqual(c.execute('SELECT UserID FROM COURSE').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT UserID FROM "SESSION"').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],2)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(len(list((self.root/'database-backups').glob('before-erd-v2-*.sqlite3'))),1)

    def exam(self,c,eid):
        c.execute("INSERT INTO exams(id,course_id,title,settings,questions,status) VALUES(?, 'c','Exam',?,?,'published')",
          (eid,json.dumps({'material_ids':['doc'],'seconds_per_question':180}),
           json.dumps([{'id':'Q1','question':'Explain atomicity','key_points':['all or nothing'],'follow_up':'Why?'}])))

    def test_question_normalization_and_exam_scoping(self):
        self.seed()
        with connect(self.path) as c:
            self.exam(c,'e2')
            self.assertEqual(c.execute('SELECT count(*) FROM QUESTION_BANK').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT count(*) FROM EXAM_DOC').fetchone()[0],2)
            q=json.loads(c.execute("SELECT questions FROM exams WHERE id='e'").fetchone()[0])[0]
            self.assertEqual(q['key_points'],['all or nothing'])
            self.assertEqual(q['follow_up'],'Why?')
            self.assertEqual(c.execute("SELECT TimeLimit FROM EXAM WHERE ExamID='e'").fetchone()[0],180)

    def test_startup_repairs_incomplete_names_without_overwriting_surname(self):
        with connect(self.path) as c:
            c.execute("INSERT INTO users VALUES(1,'john','John Smith','student','hash','now')")
            c.execute('UPDATE "USER" SET FirstName=? WHERE UserID=1',('John Smith',))
            c.execute("INSERT INTO users VALUES(2,'jane','Jane Smith','student','hash','now')")
            c.execute('UPDATE "USER" SET FirstName=?,LastName=? WHERE UserID=2',('Jane','Jones'))
        initialize_database(self.path)
        with connect(self.path) as c:
            self.assertEqual(tuple(c.execute('SELECT FirstName,LastName FROM "USER" WHERE UserID=1').fetchone()),('John','Smith'))
            self.assertEqual(tuple(c.execute('SELECT FirstName,LastName FROM "USER" WHERE UserID=2').fetchone()),('Jane','Jones'))

    def test_transcript_atomicity_and_resume(self):
        self.seed()
        store=SessionStore(self.path)
        session=store.create('c','e',student_id=2,initial_prompt='Explain atomicity')
        store.record_turn_and_update(session['id'],'Q1','Explain atomicity','all or nothing',
          {'criterion_results':[{'status':'met'}]},[{'source':'notes.txt'}],'move_on',1,0,True)
        with connect(self.path) as c:
            for table in ('INTERACTION','RESPONSE','RESP_TRANS','EVALUATION'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertEqual(store.get(session['id'])['completed'],1)
        self.assertEqual(store.list_for_exams(['e'])[0]['messages'][1]['text'],'all or nothing')
        # Invalid JSON must roll back the interaction and session progress.
        with self.assertRaises(sqlite3.OperationalError):
            with connect(self.path) as c:
                c.execute("INSERT INTO assessment_turns VALUES('bad',?,'Q1',2,'q','a','invalid','[]','move_on','','now')",(session['id'],))
        self.assertEqual(store.list_for_exams(['e'])[0]['turn_count'],1)

    def test_orphan_rejection_and_cascade(self):
        self.seed()
        with self.assertRaises(sqlite3.IntegrityError):
            with connect(self.path) as c:
                c.execute("INSERT INTO courses VALUES('bad',999,'X','X','','now')")
        with connect(self.path) as c:
            c.execute("INSERT INTO chunks(material_id,idx,text) VALUES('doc',0,'text')")
            c.execute("DELETE FROM materials WHERE id='doc'")
            self.assertEqual(c.execute('SELECT count(*) FROM DOC_CHUNKS').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM EXAM_DOC').fetchone()[0],0)

    def test_delete_exam_preserves_audit(self):
        self.seed()
        store=SessionStore(self.path)
        session=store.create('c','e',student_id=2)
        store.record_turn_and_update(session['id'],'Q1','q','a',{},[],'move_on',1,0,True)
        with connect(self.path) as c:
            c.execute("DELETE FROM exams WHERE id='e'")
            c.execute("DELETE FROM courses WHERE id='c'")
            self.assertEqual(c.execute('SELECT count(*) FROM exams').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM RESPONSE').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_migration_backup_counts_idempotent_startup(self):
        # Make real old tables from the compatibility rows, in another file.
        self.seed()
        source=self.root/'legacy.db'
        with connect(self.path) as c, sqlite3.connect(source) as legacy:
            for table in ('users','sessions','courses','materials','chunks','exams','assessment_sessions','assessment_turns'):
                cursor=c.execute(f'SELECT * FROM {table}')
                columns=[d[0] for d in cursor.description]
                legacy.execute(f'CREATE TABLE {table} ('+','.join(f'"{k}"' for k in columns)+')')
                legacy.executemany(f'INSERT INTO {table} VALUES('+','.join('?' for _ in columns)+')',cursor.fetchall())
        legacy.close()
        publications=self.root/'exams'
        publications.mkdir()
        (publications/'e.json').write_text(json.dumps({'exam_id':'e','published_at':'now','questions':[]}))
        destination=self.root/'migrated.db'
        report=migrate([source],destination,self.root/'backup',apply=False)
        self.assertFalse(destination.exists())
        self.assertEqual(report['tables']['users'],2)
        report=migrate([source],destination,self.root/'backup',apply=True)
        self.assertTrue(report['applied'])
        self.assertTrue((self.root/'backup'/'0-legacy.db').exists())
        initialize_database(destination)
        initialize_database(destination)
        with connect(destination) as c:
            self.assertEqual(c.execute('SELECT PasswordHash FROM "USER" WHERE UserID=1').fetchone()[0],'unchanged-hash')
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
        with self.assertRaises(FileExistsError):
            migrate([source],destination,self.root/'backup2',apply=True)

    def test_migration_failure_keeps_sources_and_no_target(self):
        source=self.root/'broken.db'
        with sqlite3.connect(source) as c:
            c.execute('CREATE TABLE courses(id,owner_id,code,name,term,created_at)')
            c.execute("INSERT INTO courses VALUES('bad',42,'X','X','','now')")
        c.close()
        destination=self.root/'broken-target.db'
        with self.assertRaises(sqlite3.IntegrityError):
            migrate([source],destination,self.root/'backup',apply=True)
        self.assertFalse(destination.exists())
        with sqlite3.connect(source) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM courses').fetchone()[0],1)
        c.close()

    def test_multifile_migration_preserves_transcripts_and_analytics(self):
        from rag.analytics import AnalyticsStore
        self.seed()
        sessions=SessionStore(self.path)
        s=sessions.create('c','e',student_id=2,student_name='Student',initial_prompt='q')
        sessions.record_turn_and_update(s['id'],'Q1','q','partial',{'criterion_results':[]},[],
                                        'clarify',0,1,False,'why?')
        sessions.record_turn_and_update(s['id'],'Q1','why?','complete',{'criterion_results':[{'status':'met'}]},[],
                                        'move_on',1,0,True,recording={'path':'retained.webm','format':'audio/webm'})
        analytics=AnalyticsStore(self.path,30)
        with analytics.run('assessment_turn',session_id=s['id']):
            pass
        analytics.close()
        with connect(self.path) as c:
            self.assertEqual(c.execute('SELECT AudioFilePath FROM RESP_REC').fetchone()[0],'retained.webm')
        sources=[]
        groups=(('users','sessions','courses','materials','chunks','exams'),
                ('assessment_sessions','assessment_turns'),('analytics_runs','analytics_model_calls'))
        for i,tables in enumerate(groups):
            source=self.root/f'legacy-{i}.db'
            with connect(self.path) as c:
                legacy=sqlite3.connect(source)
                try:
                    for table in tables:
                        cursor=c.execute(f'SELECT * FROM {table}')
                        columns=[d[0] for d in cursor.description]
                        legacy.execute(f'CREATE TABLE {table} ('+','.join(f'"{k}"' for k in columns)+')')
                        legacy.executemany(f'INSERT INTO {table} VALUES('+','.join('?' for _ in columns)+')',cursor.fetchall())
                    legacy.commit()
                finally:
                    legacy.close()
            sources.append(source)
        publications=self.root/'exams'
        publications.mkdir()
        payload={'exam_id':'e','published_at':'then','questions':[{'id':'Q1','question':'published version'}]}
        (publications/'e.json').write_text(json.dumps(payload))
        destination=self.root/'combined.db'
        report=migrate(sources,destination,self.root/'backup',apply=True)
        self.assertEqual(report['tables']['assessment_turns'],2)
        self.assertEqual(report['tables']['analytics_runs'],1)
        self.assertEqual(report['unresolved_links'],[])
        copied=SessionStore(destination)
        self.assertEqual(copied.get(s['id'])['current_prompt'],'')
        self.assertEqual(copied.transcripts_for_question(s['id'],'Q1'),['partial','complete'])
        with connect(destination) as c:
            self.assertEqual(read_publication(c,'e'),payload)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_migration_keeps_unresolved_legacy_session_ids(self):
        source=self.root/'old-sessions.db'
        with sqlite3.connect(source) as c:
            c.execute('''CREATE TABLE assessment_sessions(id,course_id,exam_id,student_id,student_username,student_name,
              question_index,follow_up_count,completed,current_prompt,created_at,updated_at,completed_at)''')
            c.execute("INSERT INTO assessment_sessions VALUES('s','removed-course','removed-exam',999,'old','Old Student',1,0,1,'','then','then','then')")
        c.close()
        destination=self.root/'legacy-history.db'
        report=migrate([source],destination,self.root/'backup',apply=True)
        self.assertEqual(len(report['unresolved_links']),1)
        self.assertEqual(SessionStore(destination).get('s')['student_id'],999)


if __name__=='__main__':
    unittest.main()
