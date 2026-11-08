"""Faculty Analytics drill-down: courses -> exams -> student sessions.

Read-only queries over the ERD tables (COURSE, EXAM, "SESSION", "USER").
Every function takes the signed-in professor's UserID and only returns rows
from courses that professor owns (COURSE.UserID), so one professor can never
list another professor's courses, exams, or students.

Each session row links to the attainment report (/reports/{SessionID}).
"""

from __future__ import annotations

import sqlite3

SESSION_STATUS_LABELS = {
    "active": "In progress",
    "completed": "Completed",
    "interrupted": "Interrupted",
}


def courses_for_faculty(connection: sqlite3.Connection, user_id: int) -> list[dict]:
    """The professor's courses, with how many exams and sessions each has."""
    rows = connection.execute(
        """
        SELECT c.CourseID, c.CourseCode, c.CourseName, c.Term,
               (SELECT COUNT(*) FROM EXAM e
                 WHERE e.CourseID = c.CourseID AND e.DeletedAt IS NULL) AS exam_count,
               (SELECT COUNT(*) FROM "SESSION" s JOIN EXAM e ON e.ExamID = s.ExamID
                 WHERE e.CourseID = c.CourseID AND e.DeletedAt IS NULL) AS session_count
          FROM COURSE c
         WHERE c.UserID = ?
         ORDER BY c.CourseCode COLLATE NOCASE, c.CourseName COLLATE NOCASE
        """,
        (user_id,),
    ).fetchall()
    return [
        {
            "course_id": row["CourseID"],
            "course_code": row["CourseCode"],
            "course_name": row["CourseName"],
            "term": row["Term"] or "",
            "exam_count": int(row["exam_count"] or 0),
            "session_count": int(row["session_count"] or 0),
        }
        for row in rows
    ]


def _owned_course(connection: sqlite3.Connection, user_id: int, course_id: str):
    return connection.execute(
        "SELECT CourseID, CourseCode, CourseName, Term FROM COURSE WHERE CourseID = ? AND UserID = ?",
        (course_id, user_id),
    ).fetchone()


def exams_for_course(connection: sqlite3.Connection, user_id: int, course_id: str) -> dict | None:
    """Exams in one course. Returns None if the professor does not own the course."""
    course = _owned_course(connection, user_id, course_id)
    if course is None:
        return None
    rows = connection.execute(
        """
        SELECT e.ExamID, e.ExamTitle, e.ExamStatus, e.CreatedAt, e.PublishedAt,
               COUNT(s.SessionID) AS session_count,
               SUM(CASE WHEN s.SessionStatus = 'completed' THEN 1 ELSE 0 END) AS completed_count
          FROM EXAM e
          LEFT JOIN "SESSION" s ON s.ExamID = e.ExamID
         WHERE e.CourseID = ? AND e.DeletedAt IS NULL
         GROUP BY e.ExamID
         ORDER BY coalesce(e.PublishedAt, e.CreatedAt) DESC
        """,
        (course_id,),
    ).fetchall()
    return {
        "course": {
            "course_id": course["CourseID"],
            "course_code": course["CourseCode"],
            "course_name": course["CourseName"],
            "term": course["Term"] or "",
        },
        "exams": [
            {
                "exam_id": row["ExamID"],
                "exam_title": row["ExamTitle"] or "Untitled exam",
                "exam_status": row["ExamStatus"] or "",
                "created_at": row["CreatedAt"],
                "published_at": row["PublishedAt"],
                "session_count": int(row["session_count"] or 0),
                "completed_count": int(row["completed_count"] or 0),
            }
            for row in rows
        ],
    }


def sessions_for_exam(connection: sqlite3.Connection, user_id: int, exam_id: str) -> dict | None:
    """Student sessions for one exam. Returns None if the professor does not own it."""
    exam = connection.execute(
        """
        SELECT e.ExamID, e.ExamTitle, c.CourseID, c.CourseCode, c.CourseName
          FROM EXAM e JOIN COURSE c ON c.CourseID = e.CourseID
         WHERE e.ExamID = ? AND c.UserID = ? AND e.DeletedAt IS NULL
        """,
        (exam_id, user_id),
    ).fetchone()
    if exam is None:
        return None
    rows = connection.execute(
        """
        SELECT s.SessionID, s.SessionStatus, s.StartTime, s.EndTime,
               coalesce(s.StudentID, s.UserID, s.LegacyStudentID) AS student_id,
               s.StudentUserName, s.StudentName,
               u.FirstName, u.LastName, u.DisplayName, u.UserName
          FROM "SESSION" s
          LEFT JOIN "USER" u ON u.UserID = coalesce(s.StudentID, s.UserID)
         WHERE s.ExamID = ?
         ORDER BY s.StartTime DESC
        """,
        (exam_id,),
    ).fetchall()
    sessions = []
    for row in rows:
        full_name = " ".join(part for part in (row["FirstName"], row["LastName"]) if part)
        name = full_name or row["StudentName"] or row["DisplayName"] or "Unknown student"
        status = row["SessionStatus"] or ""
        sessions.append(
            {
                "session_id": row["SessionID"],
                "student_name": name,
                "student_id": row["student_id"],
                "student_username": row["StudentUserName"] or row["UserName"] or "",
                "status": status,
                "status_label": SESSION_STATUS_LABELS.get(status, status.title() or "Unknown"),
                "start_time": row["StartTime"],
                "end_time": row["EndTime"],
            }
        )
    return {
        "course": {
            "course_id": exam["CourseID"],
            "course_code": exam["CourseCode"],
            "course_name": exam["CourseName"],
        },
        "exam": {"exam_id": exam["ExamID"], "exam_title": exam["ExamTitle"] or "Untitled exam"},
        "sessions": sessions,
    }
