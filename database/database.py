import sqlite3  # Built-in Python library for SQLite databases (works offline / air-gapped)
import os  # Built-in: helps get a file's name and extension from its path
from datetime import datetime  # Lets us get the current date and time from the computer's clock

DB_FILE = "exam_data.db"  # Name of the database file; created in this folder if missing
CHUNK_SIZE = 1500  # Max characters per material chunk; adjust once we know the LLM's limit


# ---------- Helpers (used by every function below) ----------

def get_connection():  # Opens the database with foreign keys turned on
    conn = sqlite3.connect(DB_FILE)  # Open a connection to the database file
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores FOREIGN KEY rules unless this is on
    return conn


def now():  # Current time from the computer's clock, as text like 2026-10-18 15:07:00
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- Setup ----------

def create_tables():  # Sets up all database tables (safe to run more than once)
    conn = get_connection()
    cur = conn.cursor()  # Cursor = the tool that sends SQL commands

    # sessions table: one row per exam
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- unique ID, auto-numbered
            student_name TEXT NOT NULL,                    -- who is taking the exam
            course TEXT NOT NULL,                          -- course name, e.g. CIS 484
            start_time TEXT NOT NULL,                      -- when the exam started
            end_time TEXT,                                 -- empty until the exam ends
            status TEXT NOT NULL DEFAULT 'in progress'     -- 'in progress' or 'completed'
        )
    """)

    # questions table: one row per prewritten question "card" (a card can have several parts)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            question_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- unique ID, auto-numbered
            course TEXT NOT NULL,                           -- which course, e.g. CIS 304
            question_text TEXT NOT NULL,                    -- the whole card, all parts included
            uploaded_by TEXT NOT NULL,                      -- professor's username (from the login system)
            created_at TEXT NOT NULL                        -- when it was added
        )
    """)

    # messages table: one row per thing said during an exam
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- unique ID, auto-numbered
            session_id INTEGER NOT NULL,                   -- which exam this belongs to
            speaker TEXT NOT NULL CHECK (speaker IN ('avatar', 'student')),  -- only these two
            text TEXT NOT NULL,                            -- what was said
            timestamp TEXT NOT NULL,                       -- when it was said
            audio_path TEXT,                               -- optional audio file location
            question_id INTEGER,                           -- which bank question was asked; empty for follow-ups and answers
            FOREIGN KEY (session_id) REFERENCES sessions(session_id),
            FOREIGN KEY (question_id) REFERENCES questions(question_id)
        )
    """)

    # documents table: one row per uploaded class material (the original file)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            document_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- unique ID, auto-numbered
            course TEXT NOT NULL,                           -- which course, e.g. CIS 304
            file_name TEXT NOT NULL,                        -- original name, e.g. week3_notes.pdf
            file_data BLOB NOT NULL,                        -- the actual file, stored as raw bytes
            uploaded_by TEXT NOT NULL,                      -- professor's username (from the login system)
            uploaded_at TEXT NOT NULL                       -- when it was uploaded
        )
    """)

    # document_chunks table: the material's text, split into smaller pieces for the AI
    cur.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,     -- unique ID, auto-numbered
            document_id INTEGER NOT NULL,                   -- which file this piece came from
            chunk_number INTEGER NOT NULL,                  -- order within the file (1, 2, 3...)
            text TEXT NOT NULL,                             -- the piece of text itself
            FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
        )
    """)

    conn.commit()  # Save changes (nothing is saved without this)
    conn.close()   # Close the connection


# ---------- Exam sessions and transcripts ----------

def start_session(student_name, course):  # Creates a new exam; returns its session_id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (student_name, course, start_time) VALUES (?, ?, ?)",
        (student_name, course, now())
    )
    session_id = cur.lastrowid  # The ID SQLite just gave this new session
    conn.commit()
    conn.close()
    return session_id


def save_message(session_id, speaker, text, audio_path=None, question_id=None):  # Saves one thing said
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (session_id, speaker, text, timestamp, audio_path, question_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, speaker, text, now(), audio_path, question_id)
    )
    conn.commit()
    conn.close()


def get_transcript(session_id):  # Reads back every message from one exam, in order
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT speaker, text, timestamp FROM messages WHERE session_id = ? ORDER BY message_id",
        (session_id,)  # The comma is required when there's only one value
    )
    rows = cur.fetchall()
    conn.close()  # No commit needed; we only read
    return rows


def end_session(session_id):  # Marks an exam as finished
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE sessions SET end_time = ?, status = 'completed' WHERE session_id = ?",
        (now(), session_id)
    )
    conn.commit()
    conn.close()


# ---------- Prewritten questions ----------

def save_question(course, question_text, uploaded_by):  # Adds one question card; returns its ID
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO questions (course, question_text, uploaded_by, created_at) VALUES (?, ?, ?, ?)",
        (course, question_text, uploaded_by, now())
    )
    question_id = cur.lastrowid
    conn.commit()
    conn.close()
    return question_id


def get_questions(course):  # Gets all question cards for one course, in the order they were added
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT question_id, question_text FROM questions WHERE course = ? ORDER BY question_id",
        (course,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------- Class materials ----------

def extract_text(file_path):  # Pulls the readable words out of a .pdf, .docx, or .txt file
    extension = os.path.splitext(file_path)[1].lower()  # e.g. ".pdf"

    if extension == ".pdf":
        from pypdf import PdfReader  # Needs: pip install pypdf
        reader = PdfReader(file_path)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)  # One block per page

    if extension == ".docx":
        from docx import Document  # Needs: pip install python-docx
        doc = Document(file_path)
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())  # One block per paragraph

    if extension == ".txt":
        with open(file_path, encoding="utf-8") as f:
            return f.read()

    raise ValueError(f"Unsupported file type: {extension} (use .pdf, .docx, or .txt)")


def chunk_text(text, chunk_size=CHUNK_SIZE):  # Splits long text into pieces of at most chunk_size characters
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]  # Split on blank lines

    # Step 1: cut any paragraph that is too long on its own (common with PDF pages) at a space
    pieces = []
    for p in paragraphs:
        while len(p) > chunk_size:
            cut = p.rfind(" ", 0, chunk_size)  # Last space before the limit, so words aren't split
            if cut <= 0:
                cut = chunk_size  # No space found; cut exactly at the limit
            pieces.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            pieces.append(p)

    # Step 2: group pieces into chunks without going over the limit
    chunks = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > chunk_size:  # Adding this would be too long
            chunks.append(current)  # Save the full chunk
            current = piece         # Start a new one
        else:
            current = current + "\n\n" + piece if current else piece
    if current:
        chunks.append(current)  # Save the last chunk
    return chunks


def save_document(course, file_path, uploaded_by):  # Stores a material file + its text chunks; returns its ID
    file_name = os.path.basename(file_path)  # e.g. "week3_notes.pdf"
    with open(file_path, "rb") as f:  # "rb" = read the raw bytes
        file_data = f.read()

    # Extract and chunk BEFORE touching the database, so a bad file never leaves half-saved data
    text = extract_text(file_path)
    if not text.strip():
        raise ValueError(f"No text found in {file_name}. It may be a scanned image.")
    chunks = chunk_text(text)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO documents (course, file_name, file_data, uploaded_by, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (course, file_name, file_data, uploaded_by, now())
    )
    document_id = cur.lastrowid
    for number, chunk in enumerate(chunks, start=1):  # Number chunks 1, 2, 3... to keep their order
        cur.execute(
            "INSERT INTO document_chunks (document_id, chunk_number, text) VALUES (?, ?, ?)",
            (document_id, number, chunk)
        )
    conn.commit()  # File and all its chunks are saved together
    conn.close()
    return document_id


def get_documents(course):  # Lists a course's uploaded materials (without the file bytes)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT document_id, file_name, uploaded_by, uploaded_at FROM documents "
        "WHERE course = ? ORDER BY document_id",
        (course,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_chunks(course):  # Gets all material text for one course, in order; this is what the AI reads
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT documents.file_name, document_chunks.chunk_number, document_chunks.text "
        "FROM document_chunks "
        "JOIN documents ON document_chunks.document_id = documents.document_id "
        "WHERE documents.course = ? "
        "ORDER BY documents.document_id, document_chunks.chunk_number",
        (course,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def export_document(document_id, output_path):  # Writes a stored file back to disk, byte for byte
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT file_data FROM documents WHERE document_id = ?", (document_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"No document with ID {document_id}")
    with open(output_path, "wb") as f:  # "wb" = write raw bytes
        f.write(row[0])


if __name__ == "__main__":  # Only runs when this file is run directly, not when imported
    create_tables()
    print("Tables created in", DB_FILE)
