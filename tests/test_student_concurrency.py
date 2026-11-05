"""Recording uploads must not wait for an assessment's Qdrant index lock."""
import asyncio
import importlib.util
import os
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from rag.analytics import AnalyticsStore
from rag.config import Settings
from rag.database import connect
from rag.faculty import FacultyAssessmentManager


class StudentConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.manager = FacultyAssessmentManager(Settings(session_db_path=root/'app.db'))
        with connect(root/'app.db') as c:
            c.execute("INSERT INTO users VALUES(2,'student','Student','student','hash','now')")
        self.session = self.manager.sessions.create('course', student_id=2)
        with patch.dict(os.environ, {'RECORDINGS_DIR': str(root/'recordings')}), \
             patch.dict('sys.modules', {'faster_whisper': SimpleNamespace(WhisperModel=object)}):
            spec = importlib.util.spec_from_file_location('student_concurrency_app', Path(__file__).resolve().parents[1]/'speech-to-text/app.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.app = self.module.app
        self.app.dependency_overrides[self.module.require_portal_student] = lambda: {'id': 2}
        self.app.state.manager = self.manager
        self.app.state.settings = Settings(session_db_path=root/'app.db')
        self.app.state.analytics = AnalyticsStore(root/'app.db', 30)
        self.addCleanup(self.app.state.analytics.close)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_recording_events_and_chunks_never_open_index(self):
        sid = self.session['id']
        with patch.object(self.manager, 'engine_for_session', side_effect=AssertionError('Recording opened index')):
            started = self.client.post(f'/api/sessions/{sid}/recording-events', json={
                'event': 'recording_start', 'timestamp': '2026-01-01T00:00:00Z'})
            self.assertEqual(started.status_code, 200, started.text)
            uploaded = self.client.post(f'/api/sessions/{sid}/recording-chunks/0',
                                        files={'video': ('chunk.webm', b'video segment', 'video/webm')})
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
        saved = self.module.RECORDINGS_DIR/sid/'000000.part'
        self.assertEqual(saved.read_bytes(), b'video segment')

    def test_recording_routes_still_check_session_ownership(self):
        self.app.dependency_overrides[self.module.require_portal_student] = lambda: {'id': 3}
        sid = self.session['id']
        event = self.client.post(f'/api/sessions/{sid}/recording-events', json={
            'event': 'recording_start', 'timestamp': '2026-01-01T00:00:00Z'})
        chunk = self.client.post(f'/api/sessions/{sid}/recording-chunks/0',
                                 files={'video': ('chunk.webm', b'video', 'video/webm')})
        self.assertEqual(event.status_code, 403)
        self.assertEqual(chunk.status_code, 403)
        self.assertFalse((self.module.RECORDINGS_DIR/sid).exists())

    def test_waiting_for_index_does_not_block_http_event_loop(self):
        async def exercise():
            loop_thread = threading.get_ident()
            acquired = threading.Event()
            release = threading.Event()

            def blocked_engine(*args):
                self.assertNotEqual(threading.get_ident(), loop_thread)
                acquired.set()
                if not release.wait(timeout=3):
                    raise AssertionError('HTTP loop could not release the waiting index')
                raise ValueError('Test index released')

            async def probe():
                return {'ok': True}
            self.app.add_api_route('/test-probe', probe)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test') as client:
                with patch.object(self.manager, 'engine_for_session', side_effect=blocked_engine):
                    answer = asyncio.create_task(client.post('/api/answers', data={
                        'session_id': self.session['id'], 'interaction_id': 'turn',
                        'response_start': '2026-01-01T00:00:01Z', 'response_end': '2026-01-01T00:00:02Z'},
                        files={'audio': ('answer.webm', b'voice', 'audio/webm')}))
                    try:
                        self.assertTrue(await asyncio.to_thread(acquired.wait, 2))
                        self.assertFalse(answer.done())
                        response = await asyncio.wait_for(client.get('/test-probe'), timeout=1)
                        self.assertEqual(response.status_code, 200)
                    finally:
                        release.set()
                        result = await answer
                    self.assertEqual(result.status_code, 400)
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
