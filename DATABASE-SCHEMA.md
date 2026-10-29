# Current database location

The live database was transferred and verified on October 29, 2026:

`C:\Users\logan\Downloads\Project484\CIS484_26Fap_Team7\runtime\assessment.sqlite3`

Double-click `Open-Database.cmd` in the project folder to edit this file in
Windows DB Browser for SQLite. Stop both services before editing, select
**Write Changes** to save, and close DB Browser before starting the application.
The normal launcher passes the same Windows-mounted path to both WSL services.
It selects DELETE journal mode for this shared file; Linux-only deployments
can continue using WAL. APP_DB_JOURNAL_MODE controls this setting.

The original WSL database is retained as a historical copy and is no longer the
normal launcher's write target. A consistent backup and transfer report are in
`local-backups/database-to-windows-20261029-144416-854617/`. The transfer included
committed WAL contents, preserved all schema/data, and passed integrity and
foreign-key checks. The database already contains schema version 2.

The historical paths and migration status below describe the earlier setup.

---

# Unified assessment database — revised ERD (schema version 2)

The application uses one SQLite file, selected by `APP_DB_PATH`. On this laptop
the normal launcher sets it to
`/home/logan/.local/share/ai-oral-exam/runtime/assessment.sqlite3`.
Docker uses `/data/assessment.sqlite3`; the server example uses
`/var/lib/capstone/assessment.sqlite3`.

## ERD implementation

`rag/database.py` defines the schema, foreign keys, indexes, and compatibility
views. Accounts, authentication, faculty authoring, assessment sessions,
transcripts, and operational analytics share this file. Connections enable
foreign keys and a busy timeout; the database uses WAL mode.

| ERD entity | Stored data |
| --- | --- |
| USER, AUTH_SESSION | Existing usernames, password hashes, roles, and hashed login tokens |
| USER identity fields | FirstName, LastName, and Email live directly in USER; separate PROFESSOR/STUDENT tables are removed |
| DEPARTMENT, USER_DEPART | Departments and professor memberships |
| COURSE, USER_COURSE | Course ownership and optional student enrollment |
| AVATAR | One avatar per user (UNIQUE UserID), with photo/voice paths |
| COURSE_DOC, DOC_CHUNKS | Document metadata, original file location, and extracted text chunks |
| EXAM, EXAM_DOC | Exam settings, course, publication information, and source documents |
| QUESTION_BANK | One row per exam question, with source, order, rubric, and follow-up data |
| SESSION | Student/exam links, progress, current prompt, and start/end times |
| INTERACTION | Actual question asked, sequence, selected next action, and retrieval evidence |
| RESPONSE, RESP_TRANS | Answer timestamps and transcribed answer text |
| RESP_REC | Persistent student recording paths and metadata for answer reports |
| EVALUATION | Grading results, evidence, feedback, and any supplied numeric rating |

Three extensions preserve current behavior: `EXAM_PUBLICATION` stores the last
published payload separately from editable drafts; `analytics_runs` and
`analytics_model_calls` retain operational measurements; `schema_migrations`
tracks schema versions. Question/rubric details and evaluation evidence remain
JSON inside their related rows so existing model output is preserved exactly.
Exam settings also retain their original payload for API compatibility.

Question IDs are scoped by exam internally (`exam-ID:question-ID`) because the
old application can reuse a question ID in different exams. APIs still return
the original question ID. INTERACTION records the actual prompt, including
follow-ups, independently of subsequent draft edits.

The duplicated InteractionID in the ERD's RESPONSE box is implemented as one
foreign key. Login sessions use AUTH_SESSION; assessment sessions use SESSION.
Role values remain `faculty` and `student`, preserving existing authorization.
COURSE.UserID, SESSION.UserID, AVATAR.UserID, USER_COURSE.UserID, and
USER_DEPART.UserID all reference USER directly. COURSE_DOC no longer carries
a separate ProfessorID. Missing email/department/enrollment data remains empty.

Account creation accepts `--first-name`, `--last-name`, and `--email`. CSV imports
accept `first_name`, `last_name`, and `email` columns. The existing `--name` input
remains supported: its first word becomes FirstName and the remainder LastName.
Upgrades prefer existing separate name fields, using that same display-name
fallback only when neither name field exists. DisplayName and operational
metadata remain for compatibility with existing pages/APIs.

## Compatibility and behavior

Legacy SQL names (`users`, `sessions`, `courses`, `materials`, `chunks`, `exams`,
`professor_media`, `assessment_sessions`, and `assessment_turns`) are views over
the new tables, not duplicate stores. Write triggers translate old operations
into relational writes. The session store saves an interaction, response,
transcript, evaluation, optional recording metadata, and progress in one
transaction. Full question JSON round-trips through QUESTION_BANK.

Authentication hashing and cookies, faculty ownership checks, question import,
rubrics, follow-up decisions, student response formats, and student response formats are preserved. Student recordings are now always retained for reporting. Draft edits do not affect the published snapshot.
Published JSON files remain exports; student and faculty APIs now read the
published payload from the unified database.

Deletion removes an exam from the active application while retaining its audit
record and answers. Course deletion unlinks retained historical exam/session
rows. Documents and their chunks/junction rows cascade together. Foreign keys
prevent deleting a user who still owns courses or avatar records; transfer
ownership/archive those records before removing that account.

Uploaded files, photo/voice files, recordings, generated media, and model weights
remain files. Qdrant remains the derived vector search index. Their locations
are recorded in the relational store where relevant; rebuilding/replacing model
or vector storage is outside this database migration.

The unused `database/database.py` prototype and separate `oral_exam_verify/`
Flask demo are not production application stores. Their files are left alone.

## Migration

Stop both services first. The normal `Start-Local.cmd` launcher invokes
`pipeline.py`, which prepares the database before starting either child service.
On the first launch, it imports the legacy faculty, sessions, and analytics
files, including the existing published JSON snapshots. Original source files
are retained and receive no writes from migration.

`APP_DB_PATH` must name a new destination. `DB_PATH`, `SESSION_DB_PATH`, and
`ANALYTICS_DB_PATH` are legacy migration inputs when APP_DB_PATH is configured.
Optional `LEGACY_FACULTY_DB_PATH`, `LEGACY_SESSION_DB_PATH`, and
`LEGACY_ANALYTICS_DB_PATH` override those inputs. Both services subsequently
use APP_DB_PATH. Directly starting an individual service against an old database
is refused; run the migration or normal pipeline first.

For an explicit dry run in WSL:

```bash
cd /mnt/c/Users/logan/Downloads/Project484/CIS484_26Fap_Team7
~/.local/share/ai-oral-exam/venvs/main/bin/python scripts/migrate-database.py \
  --source faculty-portal/exam_builder.db \
  --source ~/.local/share/ai-oral-exam/runtime/sessions.sqlite3 \
  --source ~/.local/share/ai-oral-exam/runtime/analytics.sqlite3 \
  --destination ~/.local/share/ai-oral-exam/runtime/assessment.sqlite3 \
  --publications-dir faculty-portal/exams
```

Include only source files that actually exist. Add `--apply` to install the
verified destination. The normal launcher automatically includes existing
sources. Migration takes consistent SQLite backups (including committed WAL
data), builds a separate file, verifies copied values and row counts, runs
foreign-key/integrity checks, and atomically publishes the destination. It
refuses existing destinations, conflicting IDs, unknown source columns, invalid
relationships, or missing published snapshots. Failures leave sources intact.

Backups and `migration-report.json` are under `database-backups/` beside the
new file. Missing relationships in historical assessment sessions are retained
as explicit legacy identifiers, with nullable live foreign keys, and listed in
the report. This preserves old transcripts when their course, account, or exam
has already been deleted. It does not create fake courses or accounts.

After a successful migration, later launches validate the schema version and
reuse the destination; they never reimport legacy files. Archive legacy files
only after verifying the migrated application and retaining a backup.

## Verification and rollback

Tests cover normalized question storage, exam-specific IDs, foreign-key
enforcement, rollback of incomplete answer writes, transcript ownership,
follow-up/progress behavior, account login, single-avatar replacement, publication/draft
isolation, migration of multiple databases, unchanged password hashes, backups,
and repeat initialization. Run `python -m unittest discover -s tests -v` using
the application's Python environment.

The actual faculty database has passed a migration dry run. WSL access was
blocked during implementation, so the actual Linux session/analytics migration
and real-model runtime verification remain pending until the normal launcher
can run. No production data has been switched during this chat.

For rollback, stop both services, preserve the new database including its WAL
via SQLite's backup API, restore the previous application code and launcher
configuration, and use the original legacy files/backups. New activity created
after migration will not automatically appear in the old schema; preserve it
and plan an explicit reverse migration before reverting an active installation.


## Updating an existing version 1 unified database

Stop both services and restart through Start-Local.cmd. Before opening the
services, initialization makes a consistent backup named
`database-backups/before-erd-v2-<timestamp>.sqlite3`, builds and validates a
version 2 database, and replaces the old file. Account IDs, password hashes,
course ownership, department memberships, enrollment, sessions, answers,
publications, and analytics are retained. Separate STUDENT/PROFESSOR tables and
their creation triggers are removed. Current avatar rows are retained once per
user; previous file assets are left untouched. Initialization is safe to repeat.

Every exam now resolves the owner's current avatar when loaded. Replacing it
affects existing exams too, matching the revised one-avatar-per-user design.
Saved JSON exports may contain the avatar reference from their publication date;
the application's database reader uses the current avatar. MediaVersion remains
internal cache metadata rather than a separate avatar row.

The code and version 1 upgrade passed 32 tests. WSL execution is still blocked
in this chat, so the live database upgrade must run on the next normal restart.


## Report recordings

Submitted student audio is retained and linked from RESPONSE through RESP_REC.
Faculty transcript responses include an authenticated recording URL, format,
and optional duration. GET /api/recordings/{recording_id} checks course ownership;
students and unrelated faculty cannot retrieve another course's audio. The
transcript page includes a player and a download link for each saved recording.
The RETAIN_AUDIO deletion switch is removed. Deleted historical audio is not
recoverable from transcripts.
