"""Student verification for the AI oral examiner.

Flow:  /login  ->  /capture (webcam photo)  ->  /exam  ->  /report

* /login   checks username + password against your students table.
* /capture takes a webcam photo in the browser and saves it on the server.
* /report  shows the student's details, the photo, and the exam result.

Edit the "SCHEMA SETTINGS" block below to match your existing database.
"""
import base64
import binascii
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
MAX_FAILED_LOGINS = 5                      # per username+IP
LOCKOUT_SECONDS = 300

app = Flask(__name__)
# Set EXAM_SECRET_KEY in production so sessions survive restarts.
app.secret_key = os.environ.get("EXAM_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("EXAM_HTTPS", "0") == "1",
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)

# A real hash to compare against when the username doesn't exist, so a
# wrong username and a wrong password take about the same time.
_DUMMY_HASH = "scrypt:32768:8:1:" + "0" * 16 + "$" + "0" * 128

_failed = {}   # (username, ip) -> [count, first_failure_time]


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


def init_session_table():
    """Adds the table that tracks each exam attempt (safe to run repeatedly)."""
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
        sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Bad or missing CSRF token. Reload the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "student_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


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
                session.clear()
                session["student_id"] = row["id"]
                session["student_name"] = row["full_name"]
                cur = get_db().execute(
                    "INSERT INTO exam_sessions (student_id, started_at) VALUES (?, ?)",
                    (row["id"], now_iso()),
                )
                get_db().commit()
                session["exam_session_id"] = cur.lastrowid
                return redirect(url_for("capture"))

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
    return render_template("capture.html", name=session["student_name"])


@app.route("/capture/photo", methods=["POST"])
@login_required
def save_photo():
    data_url = (request.get_json(silent=True) or {}).get("image", "")
    prefix = "data:image/jpeg;base64,"
    if not data_url.startswith(prefix):
        return jsonify(ok=False, error="Expected a JPEG image."), 400
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        return jsonify(ok=False, error="Image data was corrupted."), 400
    if len(raw) > MAX_PHOTO_BYTES:
        return jsonify(ok=False, error="Image is too large."), 413
    if not raw.startswith(b"\xff\xd8\xff"):
        return jsonify(ok=False, error="That isn't a JPEG file."), 400

    # Filename is built only from server-side values, never user input.
    sid = session["exam_session_id"]
    filename = f"session{sid}_student{session['student_id']}.jpg"
    with open(os.path.join(PHOTO_DIR, filename), "wb") as f:
        f.write(raw)

    db = get_db()
    db.execute(
        "UPDATE exam_sessions SET photo_path = ?, photo_taken_at = ? "
        "WHERE id = ? AND student_id = ?",
        (filename, now_iso(), sid, session["student_id"]),
    )
    db.commit()
    return jsonify(ok=True, next=url_for("exam"))


def _current_exam_session():
    row = get_db().execute(
        "SELECT * FROM exam_sessions WHERE id = ? AND student_id = ?",
        (session.get("exam_session_id"), session["student_id"]),
    ).fetchone()
    if row is None:
        abort(404)
    return row


@app.route("/exam")
@login_required
def exam():
    if not _current_exam_session()["photo_path"]:
        return redirect(url_for("capture"))
    # >>> Your AI oral examiner plugs in here. <<<
    return render_template("exam.html", name=session["student_name"])


@app.route("/exam/finish", methods=["POST"])
@login_required
def finish_exam():
    db = get_db()
    db.execute("UPDATE exam_sessions SET ended_at = ? WHERE id = ? AND student_id = ?",
               (now_iso(), session["exam_session_id"], session["student_id"]))
    db.commit()
    return redirect(url_for("report"))


@app.route("/report")
@login_required
def report():
    ex = _current_exam_session()
    return render_template("report.html", ex=ex, name=session["student_name"])


@app.route("/report/photo")
@login_required
def report_photo():
    ex = _current_exam_session()
    if not ex["photo_path"]:
        abort(404)
    return send_file(os.path.join(PHOTO_DIR, os.path.basename(ex["photo_path"])),
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
    else:
        print("WARNING: no cert.pem/key.pem found - serving plain HTTP. "
              "Webcam capture will only work from this machine (localhost).")
    app.run(host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", 5000)),
            ssl_context=(cert, key) if use_tls else None)
