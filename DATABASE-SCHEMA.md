# Shared assessment database — ERD version 3

The production application uses one SQLite file:

`C:\Users\logan\Downloads\Project484\CIS484_26Fap_Team7\runtime\assessment.sqlite3`

`APP_DB_PATH` selects this file for authentication, faculty authoring, student
sessions, transcripts, grading, and analytics. `Start-Local.cmd` passes the same
Windows-mounted path to both WSL services and selects DELETE journal mode so
Windows DB Browser can open it. Docker uses `/data/assessment.sqlite3`.
`APP_DB_JOURNAL_MODE` accepts DELETE or WAL; Linux-only deployments may use WAL.

Double-click `Open-Database.cmd` to inspect the shared file. Stop both services
and close DB Browser before migrating. In DB Browser, use **Write Changes** to
save edits and close the program before restarting the application.

## Canonical tables

The November 3 ERD is implemented in `rag/schema_v3.sql`; `rag/database.py`
initializes it and supplies the existing application adapters.

| ERD table | Purpose |
| --- | --- |
| USER, AUTH_SESSION | Accounts, password hashes, identity details, and hashed login tokens |
| INSTRUCTOR | Shared USER identity, optional department, face image, voice sample, and media cache metadata |
| STUDENT | Shared USER identity for a student |
| DEPARTMENT, COURSE | Department and course data; Course.UserID retains the faculty owner used for authorization |
| SECTION, STUDENT_SEC | Course sections, teaching instructor, and student enrollment |
| EXAM, EXAM_DOC | Exam settings and selected source documents |
| COURSE_DOC, DOC_CHUNKS | Original document metadata and extracted text chunks |
| QUEST_BANK, QUEST_ESS | Banks belonging to an exam and individual essay questions belonging to a bank |
| SESSION | Student, instructor, exam, progress, status, and session times |
| INTERACTION | Actual question asked, sequence, action, retrieval evidence, and optional timing |
| RECORDING | Original recording path and its assessment session |
| CLIP_RESP | Response clip linked to an interaction and, for audio answers, its parent recording |
| CLIP_TRANS | Clip transcript and its evaluation JSON, with preserved rating/feedback fields |

`INSTRUCTOR.InstructorID` and `STUDENT.StudentID` are shared primary/foreign keys
to USER.UserID. New accounts automatically receive the profile matching their
existing `faculty` or `student` role. Historical accounts that have both taught
and taken a practice assessment may retain both profiles; login authorization
continues to use USER.Role.

Existing functional extensions remain in this same file: EXAM_PUBLICATION,
schema_migrations, analytics_runs, and analytics_model_calls. The published exam
snapshot remains separate from its editable draft. Operational fields and JSON
retain rubrics, follow-up data, grading evidence, ownership, and cache versions.
These are deliberate extensions to the ERD, not separate databases.

## Approved relationship corrections and retained behavior

- SECTION contains CourseID referencing COURSE. It has no StudentID; STUDENT_SEC
  provides the many-to-many student/section relationship. Section numbers are
  unique within a course.
- INTERACTION reaches EXAM through SESSION.ExamID. No duplicate ExamID is stored
  on an interaction.
- CLIP_RESP uses RecordingID as the unambiguous foreign-key name for the ERD's
  `Recording (FK)` field. Its primary key is RespClip, matching the diagram;
  CLIP_TRANS.RespClipID references it.
- Typed answers retain a CLIP_RESP and CLIP_TRANS without audio. RecordingID and
  AudioFilePath are nullable for those answers. No fictional recording is made.
- One recording can have multiple clips, one interaction can have multiple
  clips, and each clip can have multiple transcripts. Legacy report APIs expose
  one evaluated response per interaction: the latest AnsweredAt/RespClip and
  latest evaluated transcript. All underlying clips/transcripts remain stored.
- Clip offsets are seconds within the recording. Unknown offsets and recording
  or interaction timing remain NULL. Start/end constraints reject negative or
  reversed clip offsets. Cross-session recording/interaction links are rejected,
  including edits to either parent session link.
- Existing submitted answer files each become one RECORDING and one CLIP_RESP.
  The application continues recording answers individually; this migration does
  not introduce continuous whole-exam audio capture or a new section-management UI.
- Historical course enrollments receive an explicitly named `legacy` section
  only when needed. Real section numbers are not inferred. This laptop had no
  preexisting enrollment rows to convert.
- Bank DocSource and unknown department/section/timing values remain empty
  unless known. Per-question source metadata is retained. New application exams
  receive a default bank named `bank:<exam-id>`.

Question IDs remain internally scoped by exam (`exam-id:question-id`) to
preserve reused external IDs. APIs continue to return the original IDs. Sessions
retain explicit legacy identifiers when historical accounts/courses/exams have
already been removed, without inventing replacement accounts or courses.

## Compatibility without duplicate storage

Old names USER_DEPART, USER_COURSE, AVATAR, QUESTION_BANK, RESPONSE, RESP_TRANS,
RESP_REC, and EVALUATION are views over the new tables. Existing `users`,
`sessions` (authentication), `courses`, `materials`, `chunks`, `exams`,
`professor_media`, `assessment_sessions`, and `assessment_turns` also remain
views. Application write triggers save directly into the canonical ERD tables.
The old enrollment adapter creates an explicit legacy section when importing
course-level enrollments.

SessionStore commits the interaction, clip, transcript, evaluation, optional
recording metadata, and session progress in one transaction. Invalid JSON,
invalid links, or a failed recording insert rolls back the whole submitted turn.
Faculty recording URLs retain course ownership checks; a recording is not
made public by the schema change. Existing avatar paths and media versions move
to INSTRUCTOR; current-avatar resolution still applies to published exams.

Uploaded documents, audio, face/voice files, generated video, and model weights
remain ordinary files. Qdrant remains a derived search index. This request keeps
one application relational database; it does not move media bytes or vector
index internals into SQLite. Backups and unused historical demo/prototype
databases are not application write targets and are retained for recovery.

## Migration and recovery

Stop both services and close DB Browser before a schema upgrade. The normal
launcher calls rag.bootstrap.prepare_database before starting either service.
Version 2 upgrades automatically through rag.erd_upgrade.upgrade_v2:

1. Make a consistent SQLite backup, including committed WAL data, beside the
   live file under `database-backups/before-erd-v3-<timestamp>.sqlite3`.
2. Build the new schema in a temporary staging file and map existing data.
3. Preserve every original table/view row through its new table or compatibility
   view; compare every original field, including hashes and exact JSON text.
   Preserve operational extension tables, their indexes/triggers, and sequence
   high-water marks. Abort on unmappable data, including more than one department
   membership for an instructor, rather than dropping data.
4. Run SQLite integrity and foreign-key checks. Recheck original rows to detect
   intervening writes, checkpoint journals, close connections, and replace the
   original database at the same path. Services must stay stopped throughout.
5. Save a sibling `.report.json` containing verified row counts and backup path.

Subsequent startup reuses schema version 3 and never reimports the old databases.
A version 1 unified file first passes through the existing v1-to-v2 conversion
using the frozen `rag/schema_v2.sql`, then through v3. Its v2 and v3 backups are
both retained. A schema newer than this application's version is refused.

For pre-unification installations, `scripts/migrate-database.py` still supports
a dry run with repeated `--source` arguments, a new `--destination`, and optional
`--publications-dir`; add `--apply` to publish. This initial import refuses to
overwrite an existing destination. The normal launcher uses existing legacy
files as migration inputs only, then all components share APP_DB_PATH.

For rollback, stop both services and preserve current data with SQLite's backup
API before restoring the pre-v3 backup and matching pre-v3 application code.
New post-upgrade activity cannot be represented automatically in the old schema;
retain it and plan a reverse migration before reverting an active installation.

## Verification

Run `python -m unittest discover -s tests -v` with the application dependencies
installed. Tests cover v1/v2 migration, exact value preservation, idempotent
startup, conflicting department rollback, section/recording foreign keys,
multiple clips/transcripts, atomic answer writes, draft/publication isolation,
login, avatar replacement, recording ownership, question import, sessions, and
analytics. These tests use temporary databases and mocked model calls; they do
not exercise real Whisper/LLM/TTS/avatar inference.
