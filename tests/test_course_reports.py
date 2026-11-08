import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag.course_reports import courses_for_faculty, exams_for_course, sessions_for_exam
from rag.database import connect, initialize_database

NOW = "2026-11-07T15:00:00+00:00"


class CourseReportsTests(unittest.TestCase):
    """Analytics drill-down: courses -> exams -> sessions, owner-only."""

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "assessment.sqlite3"
        initialize_database(self.path)
        with connect(self.path) as c:
            c.executescript(
                f"""
                INSERT INTO "USER"(UserID,UserName,PasswordHash,Role,DisplayName,CreatedAt,FirstName,LastName)
                VALUES (1,'babik','x','faculty','Dr. Babik','{NOW}',NULL,NULL),
                       (2,'other','x','faculty','Other Prof','{NOW}',NULL,NULL),
                       (10,'student1','x','student','Test Student','{NOW}','Jane','Doe'),
                       (11,'student2','x','student','Second Student','{NOW}',NULL,NULL);
                INSERT INTO COURSE(CourseID,UserID,CourseCode,CourseName,Term,CreatedAt)
                VALUES ('crs_304',1,'CIS304','Enterprise Architecture','Fall 2026','{NOW}'),
                       ('crs_330',2,'CIS330','Databases','Fall 2026','{NOW}');
                INSERT INTO EXAM(ExamID,CourseID,ExamTitle,ExamStatus,CreatedAt,PublishedAt,UserID)
                VALUES ('exam_a','crs_304','ERP Oral Exam','published','{NOW}','{NOW}',1),
                       ('exam_old','crs_304','Deleted Exam','published','{NOW}','{NOW}',1),
                       ('exam_b','crs_330','SQL Oral Exam','published','{NOW}','{NOW}',2);
                UPDATE EXAM SET DeletedAt='{NOW}' WHERE ExamID='exam_old';
                INSERT INTO "SESSION"(SessionID,UserID,StudentID,ExamID,CourseID,StartTime,EndTime,SessionStatus,UpdatedAt,StudentUserName,StudentName)
                VALUES ('sess-1',10,10,'exam_a','crs_304','2026-11-07T14:00:00+00:00','2026-11-07T14:20:00+00:00','completed','{NOW}','student1','Test Student'),
                       ('sess-2',11,11,'exam_a','crs_304','2026-11-07T14:30:00+00:00',NULL,'active','{NOW}','student2','Second Student'),
                       ('sess-3',10,10,'exam_b','crs_330','2026-11-07T13:00:00+00:00',NULL,'interrupted','{NOW}','student1','Test Student');
                """
            )
        self.connection = connect(self.path)

    def tearDown(self):
        self.connection.close()
        self.directory.cleanup()

    def test_professor_only_sees_own_courses_with_counts(self):
        courses = courses_for_faculty(self.connection, 1)
        self.assertEqual([c["course_code"] for c in courses], ["CIS304"])
        self.assertEqual(courses[0]["exam_count"], 1)  # deleted exam is hidden
        self.assertEqual(courses[0]["session_count"], 2)

    def test_exams_for_course_hides_deleted_and_counts_sessions(self):
        result = exams_for_course(self.connection, 1, "crs_304")
        self.assertEqual(result["course"]["course_code"], "CIS304")
        self.assertEqual([e["exam_id"] for e in result["exams"]], ["exam_a"])
        self.assertEqual(result["exams"][0]["session_count"], 2)
        self.assertEqual(result["exams"][0]["completed_count"], 1)

    def test_sessions_table_has_the_six_columns(self):
        result = sessions_for_exam(self.connection, 1, "exam_a")
        newest, oldest = result["sessions"]
        self.assertEqual(newest["session_id"], "sess-2")  # newest first
        self.assertEqual(oldest["student_name"], "Jane Doe")  # USER first/last name wins
        self.assertEqual(oldest["student_id"], 10)
        self.assertEqual(oldest["status"], "completed")
        self.assertEqual(oldest["status_label"], "Completed")
        self.assertEqual(oldest["start_time"], "2026-11-07T14:00:00+00:00")
        self.assertEqual(oldest["end_time"], "2026-11-07T14:20:00+00:00")
        self.assertEqual(newest["student_name"], "Second Student")  # falls back to SESSION.StudentName
        self.assertIsNone(newest["end_time"])
        self.assertEqual(newest["status_label"], "In progress")

    def test_other_professors_courses_and_exams_are_not_found(self):
        self.assertIsNone(exams_for_course(self.connection, 1, "crs_330"))
        self.assertIsNone(sessions_for_exam(self.connection, 1, "exam_b"))
        self.assertIsNone(sessions_for_exam(self.connection, 1, "exam_old"))  # deleted
        self.assertIsNone(exams_for_course(self.connection, 1, "missing"))

    def test_interrupted_status_label(self):
        result = sessions_for_exam(self.connection, 2, "exam_b")
        self.assertEqual(result["sessions"][0]["status_label"], "Interrupted")


if __name__ == "__main__":
    unittest.main()
