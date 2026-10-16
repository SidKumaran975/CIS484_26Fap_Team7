# Faculty Portal

Faculty upload course material, Llama 3 writes oral-exam questions, faculty review and publish.
Published exams are what the student side (avatar → XTTS v2 → Wav2Lip, answers → Faster Whisper) should ask.

Runs on **port 8001**, because `speech-to-text/app.py` (the student exam page) uses 8000.

## Run it

From the repo root, in the same Python environment as the rest of the project:

```bash
pip install -r faculty-portal/requirements.txt
cd faculty-portal
python manage_users.py add jsmith --role faculty --name "Dr. Jane Smith"   # first faculty account
python app.py                 # open http://127.0.0.1:8001/login
```

## How faculty use it

1. **Create a course** (code, name, term). Each faculty member sees only their own courses.
2. **Upload documents or a folder to that course**: slides, notes, readings. Folder-relative paths are preserved. After each upload batch, the portal chunks the saved source files, embeds them with `nomic-embed-text`, and builds that course's local Qdrant index.
3. **Build an exam**: pick the course, check which of its documents to draw from, set difficulty and question styles, and generate.
4. **Review**: edit, regenerate or delete questions, approve every one, then publish. Drafts are saved and can be reopened from the course's Exams tab or the dashboard.

Questions for a course are generated only from that course's documents. The server rejects attempts to mix in documents from another course.

## Sign-in

One login page (`/login`) for everyone. **The account decides where you go**, not a dropdown on the page, so a student can't choose "faculty":

- **Faculty** → the exam builder at `/`
- **Students** → the student exam page (`speech-to-text/app.py`, port 8000)

There's no self sign-up. Accounts are created from the server's terminal:

```bash
python manage_users.py add jsmith --role faculty --name "Dr. Jane Smith"   # prompts for a password
python manage_users.py import roster.csv           # bulk students: header row username,name[,password]
python manage_users.py passwd dukesd --generate    # reset; also signs them out everywhere
python manage_users.py remove dukesd
python manage_users.py list
```

`import` generates passwords for rows without one and writes every new login to `credentials_<timestamp>.csv`. **That file holds plaintext passwords:** hand them out, then delete it. It's git-ignored.

Security details:

- Passwords are hashed with scrypt and a per-user salt. Only the hash is stored.
- Sessions are random tokens in an `HttpOnly`, `SameSite=Strict` cookie, valid 8 hours. Only a SHA-256 of each token is stored. Sign-out and password resets end sessions on the server.
- Five wrong passwords lock that username for 5 minutes.
- Wrong usernames and wrong passwords get the same error and take the same time, so attackers can't discover which usernames exist.
- Every faculty API route checks the role on the server. Hiding a button is not the protection.
- Students who fetch an exam get only `id`, `question` and `follow_up`. `key_points` is the answer key and never reaches a student's browser.

Opening `login.html` directly as a file runs a demo with two fake accounts (`faculty` / `faculty123`, `student` / `student123`) for previewing the design.

Ollama must be running with `llama3`, the same model `text-to-speech-model/run_voice.py` uses.

Every package shared with `speech-to-text/requirements.txt` and the root `requirements.txt` is pinned to the **same version**, so installing this doesn't change anything the other stages depend on. The only new packages are `pypdf`, `python-docx`, `python-pptx`, `lxml` and `XlsxWriter`, for reading uploads.

The badge in the header shows the state:

| Badge | Meaning |
|---|---|
| `LIVE · llama3` | Server and Ollama both working |
| `LIVE · Ollama not reachable` | Run `ollama serve` |
| `Server offline` | Run `python app.py` |
| `DEMO MODE · fake data` | You opened `index.html` directly. Fine for demos, nothing is saved |

## Files

| File | What it is |
|---|---|
| `app.py` | FastAPI backend: uploads, semantic indexing, analytics, Llama 3 prompts, SQLite storage |
| `auth.py` | Accounts, password hashing, sessions, lockout (standard library only) |
| `manage_users.py` | Command line tool to add, import, reset and remove accounts |
| `login.html` | Sign-in page for students and faculty |
| `index.html` | The faculty page (no external scripts, fonts or CDNs) |
| `requirements.txt` | Pinned to match the rest of the repo |
| `install_offline.sh` | Installs on the air-gapped server from `wheels/` with no internet |
| `build_bundle.sh` | Run on an internet machine to download `wheels/` |
| `faculty-exam-builder.service` | systemd unit to run it on boot |

Not in Git (see `.gitignore`): `exam_builder.db` (accounts, sessions, material), `exams/`, `wheels/`, `credentials_*.csv`, and the shared `runtime/` course files, Qdrant indexes, sessions, media, and analytics.

## Settings (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `PORT` | `8001` | 8000 belongs to speech-to-text |
| `HOST` | `127.0.0.1` | Same as `pipeline.py`. Set `0.0.0.0` to let faculty on other machines connect (read *Known limits* first) |
| `OLLAMA_URL` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `llama3` | |
| `RAG_EMBED_MODEL` | `nomic-embed-text` | Embedding model used for each course's Qdrant index |
| `DB_PATH` | `exam_builder.db` | Shared account, course, material, and exam database |
| `FACULTY_EXAMS_DIR` | `exams/` | Published exam JSON read by the student backend |
| `FACULTY_COURSE_STORAGE` | `../runtime/faculty-courses` | Original uploaded course files |
| `FACULTY_INDEX_STORAGE` | `../runtime/faculty-indexes` | One embedded Qdrant store per course |
| `ANALYTICS_DB_PATH` | `../runtime/analytics.sqlite3` | Shared faculty and student operational analytics |
| `NUM_CTX` | `8192` | Llama 3 8B's maximum. Ollama's default is smaller and would silently cut off material |
| `LLM_TIMEOUT` | `300` | Seconds per question |
| `CORS_ORIGINS` | empty | Only needed if `index.html` is hosted on a different server |
| `STUDENT_PORT` | `8000` | Where students are sent after signing in (same host, this port) |
| `STUDENT_URL` | empty | Full URL override for the student page, e.g. `http://10.0.0.5:8000/` |
| `SESSION_HOURS` | `8` | How long a sign-in lasts |
| `COOKIE_SECURE` | `0` | Set `1` once the server is behind HTTPS |

## API

| Method | Path | Used by | Returns |
|---|---|---|---|
| GET | `/login` | everyone | sign-in page (skips to your home page if already signed in) |
| POST | `/api/login` | sign-in page | sets the session cookie, returns `role` and `redirect` |
| POST | `/api/logout` | both | ends the session |
| GET | `/api/me` | both | the signed-in user |
| GET | `/api/health` | faculty page | server + Ollama status |
| GET | `/api/courses` | faculty page | your courses with document and exam counts |
| POST | `/api/courses` | faculty page | create a course `{code, name, term}` |
| PUT | `/api/courses/{id}` | faculty page | rename or change term |
| DELETE | `/api/courses/{id}` | faculty page | deletes the course, its documents and its exams (published ones too) |
| GET | `/api/courses/{id}/materials` | faculty page | the course's documents |
| POST | `/api/courses/{id}/materials` | faculty page (multipart `file`) | upload one document to the course |
| DELETE | `/api/courses/{id}/materials/{mid}` | faculty page | remove a document |
| GET/POST | `/api/courses/{id}/index` | faculty page | inspect or rebuild that course's semantic index |
| GET | `/api/courses/{id}/exams` | faculty page | the course's drafts and published exams |
| POST | `/api/exams/generate` | faculty page | `{course_id, material_ids, ...}` → `exam_id`, draft questions. Empty `material_ids` = all course documents |
| GET | `/api/exams/{id}/edit` | faculty page | reopen a draft or published exam with its settings |
| PUT | `/api/exams/{id}` | faculty page | save draft edits without publishing |
| POST | `/api/exams/{id}/regenerate` | faculty page | one replacement question |
| POST | `/api/exams/{id}/publish` | faculty page | saved path |
| GET | `/api/exams` | **student side** (any signed-in user) | published exams |
| GET | `/api/exams/{id}` | **student side** (any signed-in user) | the exam; students get it without `key_points` |
| GET | `/api/analytics/summary` | faculty page | aggregate indexing, generation, and assessment metrics |
| GET | `/api/analytics/runs` | faculty page | recent instrumented operations |

Everything except `/login` and `/api/login` requires a session. Faculty routes return `403` for students, and a course or exam that belongs to another faculty member returns `404`.

A published exam is also written to `faculty-portal/exams/<exam_id>.json`, so other stages can read it from disk without calling the API:

```json
{
  "exam_id": "exam_102bdd86df",
  "course_id": "crs_51c62e42cb",
  "course": "CIS 484",
  "course_name": "Information Systems Capstone",
  "term": "Fall 2026",
  "title": "Midterm",
  "seconds_per_question": 180,
  "published_at": "2026-10-15T15:20:00+00:00",
  "questions": [
    {
      "id": "q_b611b982",
      "question": "Text the avatar speaks.",
      "key_points": ["What a strong answer covers"],
      "follow_up": "Probe asked after the answer, or null",
      "source_file": "lecture3.pptx"
    }
  ]
}
```

This replaces the manual `Question List.docx` + `Parser` step. The student service loads this published exam, converts `key_points` into private rubric criteria, retrieves course evidence from the course-specific Qdrant index, evaluates each spoken response, and generates a follow-up when required criteria are missing.

## How generation works

1. Uploads are converted to text (PDF, Word including tables, PowerPoint including speaker notes) and cut into ~1,500-character chunks stored in SQLite.
2. For each question, 3 chunks are picked: spread across the material, or ranked by keyword overlap with the focus topics.
3. One Llama 3 call per question with `format: "json"`. Output is validated, and bad output is retried up to 3 times.
4. Nothing reaches students until faculty approve every question and publish.

## Air-gapped Ubuntu server

`wheels/` is not in Git (45 MB of binaries). Build it on any machine with internet, then copy the whole `faculty-portal/` folder over:

```bash
# internet machine (use the server's Python version: 22.04 = 3.10, 24.04 = 3.12)
cd faculty-portal && PY_VERSIONS=3.12 bash build_bundle.sh

# air-gapped server
cd faculty-portal
bash install_offline.sh       # no internet, no system pip, no python3-venv needed
./venv/bin/python app.py
```

`install_offline.sh` checks the Python version, CPU type and wheels before doing anything, and tells you exactly what's wrong if they don't match.

### Getting Ollama and Llama 3 onto the server

Skip this if `ollama list` on the server already shows `llama3`. The rest of the pipeline needs it too, so it may already be there.

On a machine **with** internet:

```bash
curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst -o ollama.tar.zst
zstd -d ollama.tar.zst -o ollama-linux-amd64.tar      # plain .tar; the server may not have zstd
ollama pull llama3                                     # ~4.7 GB
tar -C ~/.ollama -cf llama3-models.tar models
```

On the **air-gapped** server:

```bash
sudo tar -xf ollama-linux-amd64.tar -C /usr
sudo useradd -r -s /bin/false -U -m -d /usr/share/ollama ollama
sudo mkdir -p /usr/share/ollama/.ollama
sudo tar -xf llama3-models.tar -C /usr/share/ollama/.ollama
sudo chown -R ollama:ollama /usr/share/ollama/.ollama
```

Then create `/etc/systemd/system/ollama.service` from Ollama's Linux docs (`docs/linux.mdx` in the ollama GitHub repo; save a copy before going offline) and run `sudo systemctl enable --now ollama`. If `ollama list` comes back empty, add `Environment="OLLAMA_MODELS=/usr/share/ollama/.ollama/models"` to that service file.

## Known limits

- **The two services must use the same hostname.** The student API validates the `examportal_session` cookie created by the faculty portal. Cookies are shared across ports on one hostname, but not across unrelated hostnames.
- **Plain HTTP.** Passwords cross the network unencrypted. That's fine on `127.0.0.1`. With `HOST=0.0.0.0`, put the server behind HTTPS (a reverse proxy like nginx with a self-signed or campus certificate), then set `COOKIE_SECURE=1`.
- **Lockout counters reset when the server restarts**, and they're per username, not per IP address.
- **Scanned PDFs** have no text layer, so the upload fails with a clear message. They need OCR first.
- **Question-authoring retrieval is keyword-based.** Llama 3 receives chunks chosen by keyword overlap when focus topics are provided. Student-answer evaluation uses the separate semantic Qdrant index built with `nomic-embed-text`.
- **CPU only is slow:** roughly 20 to 60 seconds per question, competing with XTTS, Wav2Lip and Whisper if they share the machine.
