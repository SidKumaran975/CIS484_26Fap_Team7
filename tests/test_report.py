import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag.report import build_attainment_report, load_turns
from rag.sessions import SessionStore

EXAM = {
    "exam_id": "exam_0123456789",
    "course": "CIS304",
    "title": "Report Test",
    "questions": [
        {
            "id": "q1",
            "question": "What is an ERP system and how does it help a business?",
            "key_points": ["One shared database", "Real-time information"],
        },
        {
            "id": "q2",
            "question": "What is the difference between ERP and ERP II?",
            "key_points": ["ERP II connects suppliers and customers"],
        },
        {"id": "q3", "question": "Name one ERP vendor.", "key_points": []},
    ],
}


def evaluation(results, uncertainty="low", misconceptions=()):
    return {
        "criterion_results": [
            {"criterion_id": cid, "status": status, "student_evidence": evidence, "reason": "r"}
            for cid, status, evidence in results
        ],
        "misconceptions": list(misconceptions),
        "missing_concepts": [],
        "uncertainty": uncertainty,
    }


class AttainmentReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.store = SessionStore(Path(self.directory.name) / "sessions.sqlite3")
        self.session = self.store.create(
            "crs_1", EXAM["exam_id"], student_username="student1", student_name="Test Student"
        )
        sid = self.session["id"]
        # q1: opening answer partly right, follow-up fills the gap.
        self.store.record_turn_and_update(
            sid, "q1", EXAM["questions"][0]["question"], "ERP uses one shared database.",
            evaluation([("q1_R1", "met", "one shared database"), ("q1_R2", "not_met", "")]),
            [], "probe", 0, 1, False, "How does that help managers?",
        )
        self.store.record_turn_and_update(
            sid, "q1", "How does that help managers?", "They get real-time data.",
            evaluation([("q1_R1", "partial", ""), ("q1_R2", "met", "real-time data")]),
            [], "move_on", 1, 0, False, EXAM["questions"][1]["question"],
        )
        # q2: weak answer, unsure grading, misconception noted.
        self.store.record_turn_and_update(
            sid, "q2", "Explain how ERP II differs from ERP.", "It's just newer.",
            evaluation([("q2_R1", "insufficient_evidence", "")], "high", ["ERP II is only a newer version"]),
            [], "clarify", 1, 1, False, "Can you say more?",
        )

    def tearDown(self):
        self.directory.cleanup()

    def report(self):
        session = self.store.get(self.session["id"])
        return build_attainment_report(EXAM, session, load_turns(self.store, session["id"]))

    def test_turns_are_grouped_under_essential_questions(self):
        report = self.report()
        q1, q2, q3 = report["questions"]
        self.assertEqual(q1["essential_question"], EXAM["questions"][0]["question"])
        self.assertEqual([e["turn_number"] for e in q1["exchanges"]], [1, 2])
        self.assertEqual(q1["exchanges"][1]["response"], "They get real-time data.")
        self.assertEqual(len(q2["exchanges"]), 1)
        self.assertFalse(q3["reached"])
        self.assertEqual(report["student_name"], "Test Student")

    def test_phrasing_shows_how_each_actual_question_was_asked(self):
        q1, q2, _ = self.report()["questions"]
        self.assertEqual(q1["exchanges"][0]["phrasing"], "Asked as written")
        self.assertEqual(q1["exchanges"][1]["phrasing"], "Follow-up: probe for missing points")
        self.assertEqual(q2["exchanges"][0]["phrasing"], "Rephrased")

    def test_key_point_keeps_best_status_across_turns(self):
        points = self.report()["questions"][0]["attainment"]["key_points"]
        self.assertEqual([p["text"] for p in points], ["One shared database", "Real-time information"])
        self.assertEqual([p["status"] for p in points], ["met", "met"])
        self.assertEqual(points[1]["turn_number"], 2)
        self.assertEqual(points[1]["evidence"], "real-time data")

    def test_summary_uncertainty_and_misconceptions(self):
        report = self.report()
        q1, q2, q3 = report["questions"]
        self.assertEqual(q1["attainment"]["summary"], "2 of 2 key points met")
        self.assertEqual(q2["attainment"]["uncertainty"], "high")
        self.assertEqual(q2["attainment"]["misconceptions"], ["ERP II is only a newer version"])
        self.assertEqual(q3["attainment"]["key_points"][0]["status"], "not_assessed")
        self.assertEqual(q3["attainment"]["summary"], "Not reached")
        self.assertEqual(report["totals"]["key_points"], 4)
        self.assertEqual(report["totals"]["key_points_met"], 2)
        self.assertEqual(report["totals"]["questions_reached"], 2)

    def test_bad_evaluation_json_does_not_break_report(self):
        turns = load_turns(self.store, self.session["id"])
        for turn in turns:
            turn["evaluation_json"] = "not json"
        report = build_attainment_report(EXAM, self.store.get(self.session["id"]), turns)
        self.assertEqual(report["questions"][0]["attainment"]["met"], 0)
        json.dumps(report)  # the API must be able to return it


    def test_answer_with_saved_audio_carries_its_clip_id(self):
        turns = load_turns(self.store, self.session["id"])
        first = turns[0]
        with self.store._connection() as connection:
            clip = connection.execute(
                "SELECT RespClip FROM CLIP_RESP c JOIN INTERACTION i USING(InteractionID) "
                "WHERE i.SessionID=? AND i.SequenceNumber=?",
                (self.session["id"], first["turn_number"]),
            ).fetchone()[0]
            connection.execute(
                "UPDATE CLIP_RESP SET AudioFilePath='/data/recordings/a.webm', Duration=12.4, "
                "FileFormat='audio/webm' WHERE RespClip=?",
                (clip,),
            )
        q1 = self.report()["questions"][0]
        self.assertEqual(q1["exchanges"][0]["recording_id"], clip)
        self.assertEqual(q1["exchanges"][0]["recording_duration"], 12.4)
        self.assertIsNone(q1["exchanges"][1]["recording_id"])  # no audio saved

    def test_question_with_saved_avatar_video_links_to_its_interaction(self):
        with self.store._connection() as connection:
            first = connection.execute(
                "SELECT InteractionID FROM INTERACTION WHERE SessionID=? ORDER BY SequenceNumber LIMIT 1",
                (self.session["id"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE INTERACTION SET ActualQuestionVid='/data/media/q1.mp4' WHERE InteractionID=?",
                (first,),
            )
        q1 = self.report()["questions"][0]
        self.assertEqual(q1["exchanges"][0]["interaction_id"], first)
        self.assertTrue(q1["exchanges"][0]["question_video"])
        self.assertFalse(q1["exchanges"][1]["question_video"])  # follow-up without a saved video
        self.assertNotIn("/data/media", json.dumps(self.report()))  # file paths never sent to the browser

    def test_questions_missing_from_published_exam_are_still_shown(self):
        edited = {**EXAM, "questions": [EXAM["questions"][0]]}  # q2 removed after the exam
        session = self.store.get(self.session["id"])
        report = build_attainment_report(edited, session, load_turns(self.store, session["id"]))
        self.assertEqual([q["question_id"] for q in report["questions"]], ["q1", "q2"])
        self.assertTrue(report["questions"][1]["reached"])
        self.assertEqual(report["questions"][1]["exchanges"][0]["response"], "It's just newer.")


if __name__ == "__main__":
    unittest.main()
