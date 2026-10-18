"""Isolated API/routing tests: no real accounts, models, or database touched."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from rag.config import Settings
from rag.media import MediaGenerator
from rag.profiles import profile_paths

ROOT = Path(__file__).resolve().parent.parent


def photo(color="red"):
    output = io.BytesIO()
    Image.new("RGB", (256, 256), color).save(output, format="PNG")
    return output.getvalue()


def voice():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x10\x00" * 16000 * 6)
    return output.getvalue()


class ProfessorMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.environment = patch.dict(os.environ, {
            "DB_PATH": str(cls.root / "faculty.db"),
            "FACULTY_EXAMS_DIR": str(cls.root / "exams"),
            "FACULTY_COURSE_STORAGE": str(cls.root / "courses"),
            "FACULTY_INDEX_STORAGE": str(cls.root / "indexes"),
            "FACULTY_MEDIA_STORAGE": str(cls.root / "profiles"),
            "ANALYTICS_DB_PATH": str(cls.root / "analytics.db"),
            "SESSION_DB_PATH": str(cls.root / "sessions.db"),
        })
        cls.environment.start()
        sys.path.insert(0, str(ROOT / "faculty-portal"))
        spec = importlib.util.spec_from_file_location("profile_test_portal", ROOT / "faculty-portal/app.py")
        cls.portal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.portal)
        for name, role in (("prof_a", "faculty"), ("prof_b", "faculty"), ("student", "student")):
            cls.portal.auth.create_user(name, name, role, "test-password-123")

    @classmethod
    def tearDownClass(cls):
        cls.portal.ANALYTICS.close()
        cls.environment.stop()
        sys.path.remove(str(ROOT / "faculty-portal"))
        cls.temp.cleanup()

    def client(self, name):
        client = TestClient(self.portal.app)
        response = client.post("/api/login", json={"username": name, "password": "test-password-123"})
        self.assertEqual(response.status_code, 200)
        self.addCleanup(client.close)
        return client

    def upload(self, client, color="red", audio=None):
        return client.post("/api/profile/media", files={
            "photo": ("face.png", photo(color), "image/png"),
            "voice": ("voice.wav", voice() if audio is None else audio, "audio/wav"),
        })

    def seed_exam(self, client, exam_id):
        course = client.post("/api/courses", json={"code": "TEST", "name": "Test course"}).json()
        cid = course["id"]
        manifest = self.portal.course_index_dir(cid).parent / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"course_id": cid, "embedding_model": self.portal.EMBED_MODEL}))
        with self.portal.db() as db:
            db.execute("INSERT INTO exams (id,course_id,status) VALUES (?,?,'draft')", (exam_id, cid))
        return {"course_id": cid, "title": "Test", "num_questions": 1,
                "questions": [{"id": "q1", "question": "Explain TCP", "key_points": ["Reliable"]}]}

    def test_access_validation_and_private_previews(self):
        self.assertEqual(TestClient(self.portal.app).get("/api/profile/media").status_code, 401)
        student = self.client("student")
        self.assertEqual(self.upload(student).status_code, 403)
        a, b = self.client("prof_a"), self.client("prof_b")
        self.assertEqual(self.upload(a, audio=b"not a WAV").status_code, 400)
        oversized = a.post("/api/profile/media", files={"photo": ("x.png", b"x" * (10 * 1024 * 1024 + 1)), "voice": ("x.wav", voice())})
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.upload(a).status_code, 200)
        self.assertEqual(self.upload(b, "blue").status_code, 200)
        self.assertNotEqual(a.get("/api/profile/media/photo").content, b.get("/api/profile/media/photo").content)
        self.assertEqual(student.get("/api/profile/media/voice").status_code, 403)
        self.assertEqual(a.get("/api/profile/media/voice").content, voice())

    def test_publish_snapshots_replacement_and_ownership(self):
        a, b = self.client("prof_a"), self.client("prof_b")
        first = self.upload(a).json()["version"]
        eid = "exam_0123456789"
        payload = self.seed_exam(a, eid)
        self.assertEqual(b.post(f"/api/exams/{eid}/publish", json=payload).status_code, 404)
        self.assertEqual(a.post(f"/api/exams/{eid}/publish", json=payload).status_code, 200)
        exam_path = self.portal.EXAMS_DIR / f"{eid}.json"
        saved = json.loads(exam_path.read_text())
        self.assertEqual(saved["examiner"]["media_version"], first)
        second = self.upload(a, "green").json()["version"]
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(exam_path.read_text()), saved)
        self.assertTrue(all(p.is_file() for p in profile_paths(saved["professor_id"], first)))
        with self.portal.db() as db:
            row = db.execute("SELECT professor_id,media_version FROM exams WHERE id=?", (eid,)).fetchone()
        self.assertEqual(row["media_version"], first)
        self.assertEqual(a.post(f"/api/exams/{eid}/publish", json=payload).status_code, 200)
        self.assertEqual(json.loads(exam_path.read_text())["examiner"]["media_version"], second)
        self.portal.init_db()  # Migration is safe to repeat.

    def test_legacy_publish_and_media_routing_cache(self):
        # A newly created faculty account without uploads still uses legacy media.
        self.portal.auth.create_user("legacy", "Legacy", "faculty", "test-password-123")
        legacy = self.client("legacy")
        payload = self.seed_exam(legacy, "exam_1111111111")
        self.assertEqual(legacy.post("/api/exams/exam_1111111111/publish", json=payload).status_code, 200)
        self.assertIsNone(json.loads((self.portal.EXAMS_DIR / "exam_1111111111.json").read_text())["examiner"])
        a, b = self.client("prof_a"), self.client("prof_b")
        va, vb = self.upload(a).json()["version"], self.upload(b, "blue").json()["version"]
        with self.portal.db() as db:
            ids = dict(db.execute("SELECT username,id FROM users"))
        generator = MediaGenerator(Settings(media_dir=self.root / "generated", media_mode="avatar"))
        commands = []
        def render(command, cwd, label):
            commands.append(command)
            output_flag = "--output" if "--output" in command else "--outfile"
            Path(command[command.index(output_flag) + 1]).write_bytes(b"media")
        ea = {"professor_id": ids["prof_a"], "media_version": va}
        eb = {"professor_id": ids["prof_b"], "media_version": vb}
        with patch.object(generator, "_run", side_effect=render):
            url_a = generator.generate("Question", ea)
            self.assertEqual(generator.generate("Question", ea), url_a)
            url_b = generator.generate("Question", eb)
            legacy_url = generator.generate("Question")
        self.assertEqual(len(commands), 6)
        self.assertEqual(len({url_a, url_b, legacy_url}), 3)
        face, audio = profile_paths(ids["prof_a"], va)
        self.assertEqual(commands[0][commands[0].index("--reference-audio") + 1], str(audio))
        self.assertEqual(commands[1][commands[1].index("--face") + 1], str(face))
        with self.assertRaises(ValueError):
            generator.generate("Question", {"professor_id": ids["prof_a"], "media_version": "0" * 64})
        with self.assertRaises(ValueError):
            profile_paths(1, "../../private")

    def test_faculty_can_only_read_transcripts_for_owned_exams(self):
        a, b = self.client("prof_a"), self.client("prof_b")
        exam_a, exam_b = "exam_2222222222", "exam_3333333333"
        self.seed_exam(a, exam_a)
        self.seed_exam(b, exam_b)
        session_a = self.portal.TRANSCRIPTS.create(
            "course-a",
            exam_a,
            student_id=3,
            student_username="student",
            student_name="Test Student",
            initial_prompt="Explain TCP.",
        )
        self.portal.TRANSCRIPTS.record_turn_and_update(
            session_id=session_a["id"], question_id="q1",
            prompt="Explain TCP.", transcript="TCP provides reliable delivery.",
            evaluation={}, retrieved=[], action="move_on", question_index=1,
            follow_up_count=0, completed=True,
        )
        self.portal.TRANSCRIPTS.create(
            "course-b", exam_b, student_name="Other Student",
            initial_prompt="Private prompt",
        )

        response = a.get("/api/transcripts")
        self.assertEqual(response.status_code, 200)
        sessions = response.json()["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["exam_id"], exam_a)
        self.assertEqual(sessions[0]["student_name"], "Test Student")
        self.assertEqual(
            sessions[0]["messages"][1]["text"],
            "TCP provides reliable delivery.",
        )
        self.assertEqual(self.client("student").get("/api/transcripts").status_code, 403)


if __name__ == "__main__":
    unittest.main()
