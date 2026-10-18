import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rag.analytics import AnalyticsStore
from rag.config import Settings
from rag.course import load_assessment
from rag.engine import AssessmentEngine
from rag.evaluator import choose_action
from rag.extractors import extract_file
from rag.faculty import assessment_from_exam
from rag.index import CourseIndex, chunk_text
from rag.media import MediaGenerator
from rag.schemas import Citation, CriterionResult, Evaluation
from rag.sessions import SessionStore

ROOT = Path(__file__).resolve().parent.parent
COURSE_DIR = ROOT / "tests" / "fixtures" / "course"


def fake_embeddings(texts: list[str]) -> list[list[float]]:
    return [[float("ACID" in text), float("HTTPS" in text), 1.0] for text in texts]


class CourseTests(unittest.TestCase):
    def test_session_database_migrates_existing_schema(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sessions.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.executescript("""
                    CREATE TABLE assessment_sessions (
                        id TEXT PRIMARY KEY, course_id TEXT NOT NULL, exam_id TEXT,
                        question_index INTEGER NOT NULL DEFAULT 0,
                        follow_up_count INTEGER NOT NULL DEFAULT 0,
                        completed INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE assessment_turns (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                        question_id TEXT NOT NULL, turn_number INTEGER NOT NULL,
                        prompt TEXT NOT NULL, transcript TEXT NOT NULL,
                        evaluation_json TEXT NOT NULL, retrieved_json TEXT NOT NULL,
                        action TEXT NOT NULL, created_at TEXT NOT NULL);
                """)
            store = SessionStore(path)
            session = store.create(
                "crs_test", "exam_0123456789", student_name="Migrated Student",
                initial_prompt="Migrated prompt",
            )
            self.assertEqual(session["student_name"], "Migrated Student")
            self.assertEqual(session["current_prompt"], "Migrated prompt")

    def test_published_exam_becomes_assessment_rubric(self):
        assessment = assessment_from_exam(
            {
                "course_id": "crs_test",
                "title": "Midterm",
                "questions": [
                    {
                        "id": "q_test",
                        "question": "Explain atomicity.",
                        "key_points": ["All operations commit or none do", "Rollback on failure"],
                    }
                ],
            }
        )
        self.assertEqual(assessment.course_id, "crs_test")
        self.assertEqual(assessment.questions[0].prompt, "Explain atomicity.")
        self.assertEqual(len(assessment.questions[0].rubric), 2)
        self.assertEqual(assessment.questions[0].rubric[0].description, "All operations commit or none do")

    def test_session_records_published_exam(self):
        with TemporaryDirectory() as directory:
            store = SessionStore(Path(directory) / "sessions.sqlite3")
            session = store.create(
                "crs_test",
                "exam_0123456789",
                student_id=7,
                student_username="student7",
                student_name="Student Seven",
                initial_prompt="Explain atomicity.",
            )
            self.assertEqual(session["exam_id"], "exam_0123456789")
            self.assertEqual(session["student_name"], "Student Seven")
            store.record_turn_and_update(
                session_id=session["id"],
                question_id="Q001",
                prompt=session["current_prompt"],
                transcript="Atomicity means all operations commit or none do.",
                evaluation={"criterion_results": []},
                retrieved=[],
                action="move_on",
                question_index=1,
                follow_up_count=0,
                completed=True,
            )
            transcripts = store.list_for_exams(["exam_0123456789"])
            self.assertEqual(len(transcripts), 1)
            self.assertTrue(transcripts[0]["completed"])
            self.assertEqual(transcripts[0]["messages"][0]["speaker"], "examiner")
            self.assertEqual(
                transcripts[0]["messages"][1]["text"],
                "Atomicity means all operations commit or none do.",
            )
            self.assertEqual(store.list_for_exams(["exam_other"]), [])

    def test_analytics_records_per_run_metrics(self):
        with TemporaryDirectory() as directory:
            store = AnalyticsStore(Path(directory) / "analytics.sqlite3", 30.0)
            try:
                with store.run("assessment_turn", session_id="session-1") as run:
                    with run.stage("rubric_evaluation"):
                        run.record_model_call(
                            operation="rubric_evaluation",
                            model="test-model",
                            input_tokens=120,
                            output_tokens=35,
                            duration_ms=12.5,
                        )
                    run.set_context(question_id="Q001")
                    run.add_metric("retrieved_chunks", 4)

                summary = store.summary()
                recent = store.recent_runs(10)
                self.assertEqual(summary["run_count"], 1)
                self.assertEqual(summary["input_tokens"], 120)
                self.assertEqual(summary["output_tokens"], 35)
                self.assertEqual(recent[0]["question_id"], "Q001")
                self.assertEqual(recent[0]["metrics"]["retrieved_chunks"], 4)
                self.assertEqual(recent[0]["stages"][0]["name"], "rubric_evaluation")
                self.assertEqual(recent[0]["model_calls"][0]["input_tokens"], 120)
            finally:
                store.close()

    def test_assessment_and_markdown_extract(self):
        assessment = load_assessment(COURSE_DIR)
        self.assertEqual(len(assessment.questions), 2)
        sections = extract_file(COURSE_DIR / "materials" / "notes.md")
        self.assertTrue(any("ACID" in section.text for section in sections))

    def test_chunking_and_decision_limit(self):
        text = " ".join(str(number) for number in range(900))
        self.assertGreaterEqual(len(chunk_text(text)), 3)
        evaluation = Evaluation(
            criterion_results=[
                CriterionResult(criterion_id="R1", status="not_met", reason="missing")
            ],
            uncertainty="low",
            suggested_follow_up="Please explain R1.",
        )
        self.assertEqual(choose_action(evaluation, {"R1"}, 0, 1), "probe")
        self.assertEqual(choose_action(evaluation, {"R1"}, 1, 1), "move_on")

    def test_local_qdrant_index(self):
        assessment = load_assessment(COURSE_DIR)
        with TemporaryDirectory() as directory:
            index = CourseIndex(Path(directory) / "qdrant", "fake-model")
            try:
                index._embed = fake_embeddings
                manifest = index.rebuild(COURSE_DIR, assessment.course_id)
                self.assertEqual(manifest["document_count"], 1)
                self.assertGreater(manifest["chunk_count"], 0)
                results = index.search("ACID transactions", 3)
                self.assertTrue(results)
                self.assertTrue(results[0].source.endswith("notes.md"))
            finally:
                index.close()

    def test_follow_up_then_next_question(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                course_content_dir=COURSE_DIR,
                vector_db_path=root / "qdrant",
                session_db_path=root / "sessions.sqlite3",
                media_dir=root / "media",
                embed_model="fake",
                evaluation_model="fake",
                top_k=2,
                max_follow_ups=1,
                media_mode="none",
            )
            engine = AssessmentEngine(settings, exam_id="exam_0123456789")
            try:
                engine.index._embed = fake_embeddings
                self.assertTrue(engine.publish_course().ready)
                session = engine.start_session()
                call_count = [0]

                def fake_evaluate(question, objectives, response, chunks):
                    call_count[0] += 1
                    status = "met" if call_count[0] > 1 else "not_met"
                    return Evaluation(
                        criterion_results=[
                            CriterionResult(
                                criterion_id=criterion.id,
                                status=status,
                                reason="test evaluation",
                            )
                            for criterion in question.rubric
                        ],
                        uncertainty="low",
                        suggested_follow_up="Can you name all four ACID properties?",
                        citations=[
                            Citation(
                                source=chunks[0].source,
                                locator=chunks[0].locator,
                                chunk_id=chunks[0].chunk_id,
                            )
                        ],
                    )

                engine.evaluator.evaluate = fake_evaluate
                first = engine.submit_response(
                    session["session_id"], "Atomicity means all or nothing."
                )
                self.assertEqual(first["action"], "probe")
                self.assertEqual(first["next_question_id"], "Q001")
                second = engine.submit_response(
                    session["session_id"],
                    "Consistency, isolation, and durability are also required.",
                )
                self.assertEqual(second["action"], "move_on")
                self.assertEqual(second["next_question_id"], "Q002")
                saved = engine.sessions.list_for_exams(["exam_0123456789"])
                prompts = [
                    message["text"]
                    for message in saved[0]["messages"]
                    if message["speaker"] == "examiner"
                ]
                self.assertEqual(prompts[0], "What is ACID compliance in database transactions?")
                self.assertEqual(prompts[1], "Can you name all four ACID properties?")
            finally:
                engine.close()

    def test_avatar_media_generation_and_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                course_content_dir=COURSE_DIR,
                vector_db_path=root / "qdrant",
                session_db_path=root / "sessions.sqlite3",
                media_dir=root / "media",
                media_mode="avatar",
                wav2lip_resize_factor=2,
            )
            generator = MediaGenerator(settings)
            commands = []

            def fake_run(command, cwd, label):
                commands.append(command)
                output_flag = "--outfile" if "--outfile" in command else "--output"
                output_path = Path(command[command.index(output_flag) + 1])
                output_path.write_bytes(b"generated media")

            with patch.object(generator, "_run", side_effect=fake_run):
                first = generator.generate("What is ACID compliance?")
                second = generator.generate("What is ACID compliance?")

            self.assertEqual(first, second)
            self.assertTrue(first.endswith(".mp4"))
            self.assertEqual(len(commands), 2)
            self.assertIn("--resize_factor", commands[1])
            self.assertEqual(
                commands[1][commands[1].index("--resize_factor") + 1], "2"
            )


if __name__ == "__main__":
    unittest.main()
