# Oral exam: student verification (air-gapped)

Login against your students table, a webcam photo of the student's ID card,
a webcam photo of their face, and an end-of-exam report showing both.
Everything runs on the exam server. The code makes no outbound network calls,
and the pages load no CDN scripts, fonts, or images, so it works with no
internet.

Flow: `/login` -> ID card photo -> face photo -> exam -> report.

**What it does not do:** it does not match the face to the ID automatically.
Both photos are stored and the session stays "pending" until an instructor
compares them and runs `review.py approve` or `review.py reject`.

## Try it on your Windows laptop (PowerShell)

Webcam capture works over plain HTTP on `localhost`, so no certificate is needed.

    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    python make_demo_db.py exam.db
    python app.py

Open http://127.0.0.1:5000 and sign in as `teststudent` / `correct horse`.
If PowerShell blocks the activate script, run
`Set-ExecutionPolicy -Scope Process Bypass` first.

To run the demo student through again, delete `exam.db` and re-run
`python make_demo_db.py exam.db` (a finished student cannot start a second
attempt unless `EXAM_ALLOW_RETAKE=1`).

## Deploy on the Ubuntu exam server (no internet)

### 1. Install dependencies

The only dependency is Flask. Pick one route.

**A. Wheels carried over on removable media** (use a machine with internet
that runs the same Ubuntu and Python version as the exam server):

    pip download -r requirements.txt -d wheels
    # copy this folder + wheels/ to the server, then on the server:
    python3 -m venv venv
    ./venv/bin/pip install --no-index --find-links wheels -r requirements.txt

**B. Ubuntu packages** (if the server has an offline apt mirror or the
Ubuntu ISO mounted as a repository):

    sudo apt install python3-flask

### 2. Create the HTTPS certificate (once)

Browsers only allow webcam access on HTTPS (or localhost). openssl ships
with Ubuntu, so no internet is needed:

    ./make_cert.sh 192.168.1.50 examserver.local   # your server's IP / hostname

`app.py` serves HTTPS automatically when `cert.pem` and `key.pem` are next
to it. Without them it serves plain HTTP on 127.0.0.1 only. Import
`cert.pem` into the lab computers' trust store to remove the browser's
self-signed warning.

### 3. Point it at your database and run

1. Edit the SCHEMA SETTINGS block at the top of `app.py` (table and column
   names; passwords must be stored as Werkzeug hashes).
2. Run:

       export EXAM_DB=/path/to/your.db
       ./venv/bin/python app.py                           # or python3 app.py for route B

   The session key is saved to `secret.key` on first run so logins survive
   restarts. Set `EXAM_SECRET_KEY` instead if you prefer to manage it.
3. Students open `https://<server-ip>:5000`.

The app adds the columns it needs to `exam_sessions` automatically.

### 4. Review identities

    python3 review.py list
    python3 review.py approve 3 --by "Dr. Lee"
    python3 review.py reject 3 --by "Dr. Lee" --note "Face does not match ID"

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `EXAM_DB` | `exam.db` next to app.py | Path to the database |
| `EXAM_PHOTO_DIR` | `photos/` | Where photos are saved |
| `EXAM_SECRET_KEY` | saved in `secret.key` | Flask session key |
| `EXAM_ALLOW_RETAKE` | `0` | `1` lets a student start a new attempt after finishing |
| `EXAM_HTTPS` | `0` | `1` marks session cookies Secure (set automatically with a cert) |
| `HOST` / `PORT` | `127.0.0.1` (or `0.0.0.0` with a cert) / `5000` | Listen address |

## Connecting the examiner

`templates/exam.html` is the placeholder where your AI examiner goes. When
grading finishes, call `record_result(session["exam_session_id"], score, notes)`
from `app.py` so the report shows the score.

## Keeping it air-gapped

- Don't add pip/npm packages or CDN links later without carrying them in the
  same offline way.
- Photos are stored in `photos/`; the database and photos stay on the server.
- Restrict who can read `key.pem`, `secret.key`, the database, and `photos/`
  (ID cards and face photos are personal data).
- Don't commit `exam.db` or `photos/` (the included `.gitignore` excludes them).
