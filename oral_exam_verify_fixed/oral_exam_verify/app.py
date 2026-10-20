"""Student verification for the AI oral examiner.

Flow:  /login -> /capture/id (student ID card) -> /capture/face -> /exam -> /report

* /login          checks username + password against your students table.
* /capture/id     takes a webcam photo of the student's ID card.
* /capture/face   takes a webcam photo of the student's face.
* /report         shows both photos side by side with the exam result.

This app does NOT match the face to the ID automatically. It records both
photos and marks the session "pending"; an instructor reviews them and
approves or rejects the session with review.py.

Edit the "SCHEMA SETTINGS" block below to match your existing database.
"""
import base64
import binascii
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, abort, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from werkzeug.security import check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("EXAM_DB", os.path.join(BASE_DIR, "exam.db"))
PHOTO_DIR = os.environ.get("EXAM_PHOTO_DIR", os.path.join(BASE_DIR, "photos"))
os.makedirs(PHOTO_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# SCHEMA SETTINGS - change these to match your existing students table.
# Passwords must be stored as hashes (werkzeug / pbkdf2 / scrypt format).
# ---------------------------------------------------------------------------
USERS_TABLE = "students"
COL_ID = "id"
COL_USERNAME = "username"
COL_PASSWORD_HASH = "password_hash"
COL_FULL_NAME = "full_name"
# ---------------------------------------------------------------------------

MAX_PHOTO_BYTES = 2 * 1024 * 1024          # 2 MB
MIN_PHOTO_WIDTH, MIN_PHOTO_HEIGHT = 320, 240
MAX_FAILED_LOGINS = 5                      # per username+IP
LOCKOUT_SECONDS = 300
# Set EXAM_ALLOW_RETAKE=1 to let a student start a new attempt after finishing.
ALLOW_RETAKE = os.environ.get("EXAM_ALLOW_RETAKE", "0") == "1"

# The two photos taken before the exam. Order matters: ID first, then face.
# kind -> (path column, taken-at column, hash column, page heading, hint)
PHOTO_KINDS = {
    "id": ("id_photo_path", "id_photo_taken_at", "id_sha256",
           "Photograph your student ID",
           "Hold your student ID card up to the camera so your name and photo "
           "are readable, with no glare."),
    "face": ("photo_path", "photo_taken_at", "face_sha256",
             "Photograph your face",
             "Look at the camera in good light. Remove hats and sunglasses."),
}
KIND_ORDER = ["id", "face"]

app = Flask(__name__)


def _load_secret_key():
    """EXAM_SECRET_KEY if set, else a key saved next to the app so that
    sessions survive restarts (and work with more than one worker)."""
    env = os.environ.get("EXAM_SECRET_KEY")
    if env:
        return env
    path = os.path.join(BASE_DIR, "secret.key")
    try:
        with open(path, "r", encoding="ascii") as f:
            key = f.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(key)
    return key


app.secret_key = _load_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("EXAM_HTTPS", "0") == "1",
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)

# A real hash to compare against when the username doesn't exist, so a
# wrong username and a wrong password take about the same time.
_DUMMY_HASH = "scrypt:32768:8:1:" + "0" * 16 + "$" + "0" * 128

_failed = {}   # (username, ip) -> (count, first_failure_time)


# ----------------------------- database ------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columns added after the first version; added to an existing table if missing.
_SESSION_COLUMNS = {
    "id_photo_path": "TEXT",
    "id_photo_taken_at": "TEXT",
    "face_sha256": "TEXT",
    "id_sha256": "TEXT",
    "verification_status": "TEXT NOT NULL DEFAULT 'pending'",
    "reviewed_by": "TEXT",
    "reviewed_at": "TEXT",
}


def init_session_table():
    """Creates / upgrades the table that tracks each exam attempt."""
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """CREATE TABLE IF NOT EXISTS exam_sessions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               student_id INTEGER NOT NULL,
               started_at TEXT NOT NULL,
               photo_path TEXT,
               photo_taken_at TEXT,
               ended_at TEXT,
               score REAL,
               notes TEXT
           )"""
    )
    have = {r[1] for r in db.execute("PRAGMA table_info(exam_sessions)")}
    for col, decl in _SESSION_COLUMNS.items():
        if col not in have:
            db.execute(f"ALTER TABLE exam_sessions ADD COLUMN {col} {decl}")
    db.commit()
    db.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------- login throttling --------------------------------
def _locked_out(key):
    entry = _failed.get(key)
    if not entry:
        return False
    count, first = entry
    if time.time() - first > LOCKOUT_SECONDS:
        _failed.pop(key, None)
        return False
    return count >= MAX_FAILED_LOGINS


def _record_failure(key):
    count, first = _failed.get(key, (0, time.time()))
    _failed[key] = (count + 1, first)


# ------------------------------- CSRF --------------------------------------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_csrf():
    if request.method == "POST":
        expected = session.get("csrf", "")
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
        # An empty expected token (no session yet) must never match.
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            abort(400, "Bad or missing CSRF token. Reload the page and try again.")


@app.after_request
def security_headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Permissions-Policy"] = "camera=(self), microphone=()"
    return resp


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "student_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# --------------------------- exam sessions ---------------------------------
def start_or_resume_session(student_id):
    """Returns the id of the student's unfinished attempt, or starts one.
    Returns None if they already finished and retakes are not allowed."""
    db = get_db()
    row = db.execute(
        "SELECT id FROM exam_sessions WHERE student_id = ? AND ended_at IS NULL "
        "ORDER BY id DESC LIMIT 1", (student_id,)).fetchone()
    if row:
        return row["id"]
    if not ALLOW_RETAKE:
        done = db.execute(
            "SELECT 1 FROM exam_sessions WHERE student_id = ? LIMIT 1",
            (student_id,)).fetchone()
        if done:
            return None
    cur = db.execute(
        "INSERT INTO exam_sessions (student_id, started_at) VALUES (?, ?)",
        (student_id, now_iso()))
    db.commit()
    return cur.lastrowid


def _current_exam_session():
    row = get_db().execute(
        "SELECT * FROM exam_sessions WHERE id = ? AND student_id = ?",
        (session.get("exam_session_id"), session["student_id"]),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def _next_missing_kind(ex):
    for kind in KIND_ORDER:
        if not ex[PHOTO_KINDS[kind][0]]:
            return kind
    return None


# ------------------------------- photos ------------------------------------
def jpeg_size(raw):
    """(width, height) read from the JPEG header, or None if unreadable."""
    i = 2
    n = len(raw)
    while i + 9 < n:
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            i += 2
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(raw[i + 5:i + 7], "big")
            width = int.from_bytes(raw[i + 7:i + 9], "big")
            return width, height
        i += 2 + int.from_bytes(raw[i + 2:i + 4], "big")
    return None


def _decode_jpeg_data_url(data_url):
    """Returns (raw_bytes, error_message, http_status)."""
    prefix = "data:image/jpeg;base64,"
    if not data_url.startswith(prefix):
        return None, "Expected a JPEG image.", 400
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        return None, "Image data was corrupted.", 400
    if len(raw) > MAX_PHOTO_BYTES:
        return None, "Image is too large.", 413
    if not raw.startswith(b"\xff\xd8\xff") or not raw.rstrip(b"\x00").endswith(b"\xff\xd9"):
        return None, "That isn't a complete JPEG file.", 400
    size = jpeg_size(raw)
    if size is None:
        return None, "Could not read the image.", 400
    if size[0] < MIN_PHOTO_WIDTH or size[1] < MIN_PHOTO_HEIGHT:
        return None, "The photo is too small. Use a clearer camera view.", 400
    return raw, None, 200


# ------------------------------- routes ------------------------------------
@app.route("/")
def index():
    return redirect(url_for("capture" if "student_id" in session else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        key = (username.lower(), request.remote_addr)

        if _locked_out(key):
            error = "Too many failed attempts. Please wait a few minutes."
        else:
            row = get_db().execute(
                f"SELECT {COL_ID} AS id, {COL_FULL_NAME} AS full_name, "
                f"{COL_PASSWORD_HASH} AS pw FROM {USERS_TABLE} "
                f"WHERE {COL_USERNAME} = ?",
                (username,),
            ).fetchone()

            stored = row["pw"] if row else _DUMMY_HASH
            try:
                password_ok = check_password_hash(stored, password)
            except ValueError:
                password_ok = False

            if row and password_ok:
                _failed.pop(key, None)
                exam_id = start_or_resume_session(row["id"])
                if exam_id is None:
                    error = ("You have already completed this exam. "
                             "Contact your instructor if you need another attempt.")
                else:
                    session.clear()
                    session["student_id"] = row["id"]
                    session["student_name"] = row["full_name"]
                    session["exam_session_id"] = exam_id
                    return redirect(url_for("capture"))
            else:
                _record_failure(key)
                # Log the real reason server-side; show the student one message
                # so the form can't be used to discover which usernames exist.
                reason = "wrong password" if row else "unknown username"
                app.logger.warning("Failed login for %r (%s) from %s",
                                   username, reason, request.remote_addr)
                error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/capture")
@login_required
def capture():
    """Sends the student to whichever photo is still missing."""
    ex = _current_exam_session()
    kind = _next_missing_kind(ex)
    if kind is None:
        return redirect(url_for("exam"))
    return redirect(url_for("capture_page", kind=kind))


@app.route("/capture/<kind>")
@login_required
def capture_page(kind):
    if kind not in PHOTO_KINDS:
        abort(404)
    ex = _current_exam_session()
    if ex["ended_at"]:
        return redirect(url_for("report"))
    if kind == "face" and not ex[PHOTO_KINDS["id"][0]]:
        return redirect(url_for("capture_page", kind="id"))
    _, _, _, heading, hint = PHOTO_KINDS[kind]
    step = KIND_ORDER.index(kind) + 1
    return render_template("capture.html", name=session["student_name"],
                           kind=kind, heading=heading, hint=hint,
                           step=step, steps=len(KIND_ORDER))


@app.route("/capture/<kind>/photo", methods=["POST"])
@login_required
def save_photo(kind):
    if kind not in PHOTO_KINDS:
        abort(404)
    path_col, taken_col, hash_col, _, _ = PHOTO_KINDS[kind]
    ex = _current_exam_session()
    if ex["ended_at"]:
        return jsonify(ok=False, error="This exam is already finished."), 409
    if kind == "face" and not ex[PHOTO_KINDS["id"][0]]:
        return jsonify(ok=False, error="Photograph your ID card first."), 409

    raw, err, status = _decode_jpeg_data_url(
        (request.get_json(silent=True) or {}).get("image", ""))
    if err:
        return jsonify(ok=False, error=err), status

    digest = hashlib.sha256(raw).hexdigest()
    other = "face" if kind == "id" else "id"
    if ex[PHOTO_KINDS[other][2]] == digest:
        return jsonify(ok=False, error="The ID photo and face photo can't be the same image."), 400

    # Filename is built only from server-side values, never user input.
    filename = f"session{ex['id']}_student{session['student_id']}_{kind}.jpg"
    with open(os.path.join(PHOTO_DIR, filename), "wb") as f:
        f.write(raw)

    db = get_db()
    db.execute(
        f"UPDATE exam_sessions SET {path_col} = ?, {taken_col} = ?, {hash_col} = ? "
        "WHERE id = ? AND student_id = ?",
        (filename, now_iso(), digest, ex["id"], session["student_id"]),
    )
    db.commit()
    nxt = "exam" if kind == KIND_ORDER[-1] else "capture"
    return jsonify(ok=True, next=url_for(nxt))


@app.route("/exam")
@login_required
def exam():
    ex = _current_exam_session()
    if ex["ended_at"]:
        return redirect(url_for("report"))
    if _next_missing_kind(ex):
        return redirect(url_for("capture"))
    # >>> Your AI oral examiner plugs in here. <<<
    return render_template("exam.html", name=session["student_name"])


@app.route("/exam/finish", methods=["POST"])
@login_required
def finish_exam():
    ex = _current_exam_session()
    if _next_missing_kind(ex):
        return redirect(url_for("capture"))
    if not ex["ended_at"]:
        db = get_db()
        db.execute("UPDATE exam_sessions SET ended_at = ? WHERE id = ? AND student_id = ?",
                   (now_iso(), ex["id"], session["student_id"]))
        db.commit()
    return redirect(url_for("report"))


@app.route("/report")
@login_required
def report():
    ex = _current_exam_session()
    if _next_missing_kind(ex):
        return redirect(url_for("capture"))
    return render_template("report.html", ex=ex, name=session["student_name"])


@app.route("/report/photo/<kind>")
@login_required
def report_photo(kind):
    if kind not in PHOTO_KINDS:
        abort(404)
    ex = _current_exam_session()
    stored = ex[PHOTO_KINDS[kind][0]]
    if not stored:
        abort(404)
    return send_file(os.path.join(PHOTO_DIR, os.path.basename(stored)),
                     mimetype="image/jpeg", max_age=0)


def record_result(session_id, score, notes=""):
    """Call this from the examiner code when grading finishes."""
    db = sqlite3.connect(DB_PATH)
    db.execute("UPDATE exam_sessions SET score = ?, notes = ? WHERE id = ?",
               (score, notes, session_id))
    db.commit()
    db.close()


init_session_table()

if __name__ == "__main__":
    # Browsers only allow webcam access on HTTPS or localhost. Run
    # ./make_cert.sh once (uses the openssl already on Ubuntu, no internet),
    # then this serves HTTPS automatically when cert.pem / key.pem exist.
    cert = os.path.join(BASE_DIR, "cert.pem")
    key = os.path.join(BASE_DIR, "key.pem")
    use_tls = os.path.exists(cert) and os.path.exists(key)
    if use_tls:
        app.config["SESSION_COOKIE_SECURE"] = True
        default_host = "0.0.0.0"
    else:
        # Plain HTTP only works for the webcam on localhost, so don't expose it.
        default_host = "127.0.0.1"
        print("WARNING: no cert.pem/key.pem found - serving plain HTTP on "
              "127.0.0.1 only. Run make_cert.sh to serve students over HTTPS.")
    app.run(host=os.environ.get("HOST", default_host),
            port=int(os.environ.get("PORT", 5000)),
            ssl_context=(cert, key) if use_tls else None)
