"""Creates a throwaway exam.db with one test student, for trying the app out.
Skip this if you're pointing the app at your real database (set EXAM_DB)."""
import sqlite3
import sys

from werkzeug.security import generate_password_hash

db = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "exam.db")
db.execute("""CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL)""")
db.execute("INSERT OR REPLACE INTO students (id, username, password_hash, full_name) VALUES (1, ?, ?, ?)",
           ("teststudent", generate_password_hash("correct horse"), "Test Student"))
db.commit()
print("Demo student: username 'teststudent', password 'correct horse'")
