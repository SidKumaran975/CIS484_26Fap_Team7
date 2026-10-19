# Oral exam: student verification (air-gapped)

Login against your students table, webcam photo, and an end-of-exam report.
Everything runs on the exam server. The code makes no outbound network calls,
and the pages load no CDN scripts, fonts, or images, so it works with no
internet.

## 1. Install dependencies without internet

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

## 2. Create the HTTPS certificate (once)

Browsers only allow webcam access on HTTPS (or localhost). openssl ships
with Ubuntu, so no internet is needed:

    ./make_cert.sh 192.168.1.50 examserver.local   # your server's IP / hostname

`app.py` serves HTTPS automatically when `cert.pem` and `key.pem` are next
to it. Import `cert.pem` into the lab computers' trust store to remove the
browser's self-signed warning.

## 3. Point it at your database and run

1. Edit the SCHEMA SETTINGS block at the top of `app.py` (table and column
   names; passwords must be stored as Werkzeug hashes).
2. Run:

       export EXAM_DB=/path/to/your.db
       export EXAM_SECRET_KEY="$(openssl rand -hex 32)"   # keep it stable across restarts
       ./venv/bin/python app.py                           # or python3 app.py for route B

3. Students open `https://<server-ip>:5000`.

To try it with a throwaway test student first: `python3 make_demo_db.py exam.db`
(username `teststudent`, password `correct horse`).

## Keeping it air-gapped

- Don't add pip/npm packages or CDN links later without carrying them in the
  same offline way.
- Photos are stored in `photos/`; the database and photos stay on the server.
- Restrict who can read `key.pem`, the database, and `photos/` (student
  face photos are personal data).
