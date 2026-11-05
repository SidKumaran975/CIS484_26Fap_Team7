# Recording ERD — schema version 6

Version 6 keeps professor questions in the question bank and stores per-turn
prompts and follow-up concepts on INTERACTION. Its backed-up migration removes
the old per-turn bank copies while preserving interaction and transcript history.

Version 5 aligns the running SQLite system with `ERD (Page 1) (10).png`.
All 19 diagram entities are physical tables. `CLIP_RESP` now uses the diagram's
`RespClip` primary key and `Recording` foreign key; `CLIP_TRANS.RespClipID`
references `CLIP_RESP.RespClip`. An exam may have multiple `QUEST_BANK` rows.
The existing authoring flow continues to use its default bank, whose BankID
equals ExamID. The migration retains all rows, validates every compatibility
view and foreign key, and saves a `before-erd-v5-*.sqlite3` backup first.

This is an operational implementation of the ERD, not an exact 19-table-only
schema. Supporting fields/tables listed below remain to preserve publishing,
authentication roles, resumable sessions, analytics, and historical data.
The separate `database/schema-snapshot-sqlserver.sql` is the 19-table diagram
inspection copy for SSMS; the running application still uses SQLite.

Implements `ERD (Page 1) (9).png` and the full/part recording definitions.
Version 4 accommodates both main's v2 database and an earlier local v3 variant.
Stop both services and close DB Browser before upgrading. Startup upgrades
automatically; the explicit alternative is:

```sh
python scripts/upgrade-recording-database.py
```

SQLite backups are written to `runtime/database-backups/`. A v2 upgrade is one
transaction, including DDL and validation. The earlier local v3 is imported into
a separate file, checked, then published atomically. Windows uses SQLite's transactional backup API to preserve the existing file permissions; other platforms replace the file. Failures retain the source.
Never run the old main branch against the upgraded file: use its matching backup
to roll back the database along with the application.

## Canonical storage

`STUDENT`, `INSTRUCTOR`, `SECTION`, `STUDENT_SEC`, `QUEST_BANK`, `QUEST_ESS`,
`RECORDING`, `CLIP_RESP`, and `CLIP_TRANS` are physical tables. The existing USER,
AUTH_SESSION, DEPARTMENT, COURSE, COURSE_DOC, DOC_CHUNKS, EXAM, EXAM_DOC, SESSION,
and INTERACTION tables remain, with the new ERD fields and relationships.

AVATAR, QUESTION_BANK, RESPONSE, RESP_TRANS, RESP_REC, and EVALUATION are
compatibility **views**, not separate authoritative stores. Existing portal and
report APIs read from the canonical data. `CLIP_RESP.Recording` implements the
diagram's recording foreign key; `RespClip` is its primary key, referenced by
`CLIP_TRANS.RespClipID`.

## Mapping issues and retained extensions

| Existing information | Mapping / limitation |
| --- | --- |
| Roles, display names, account creation dates | USER keeps Role, DisplayName, CreatedAt. The ERD's subtype tables alone do not preserve these API/authentication fields. |
| Professor avatar version | INSTRUCTOR owns photo/voice paths; MediaVersion and UpdatedAt remain for cache invalidation. |
| Multiple department memberships | USER_DEPART remains. INSTRUCTOR.DepartmentID uses the first membership by ID on migration, without deleting other memberships. |
| Course owner, term, creation date | COURSE keeps UserID, Term, CreatedAt; ownership still authorizes faculty access. |
| Course enrollment without section number | Preserved in USER_COURSE and mapped to SECTION `legacy:<course-id>` / SectionNumber `legacy-unassigned`. Actual section assignments cannot be inferred. Existing sections from the earlier local v3 are also retained. |
| Student enrollment date, academic level, major, status | No reliable source exists; new STUDENT fields remain NULL until supplied. |
| Exam settings, soft deletion, publication snapshot | SettingsJSON, DeletedAt, media/owner fields, and EXAM_PUBLICATION remain. Published exams remain independent of editable drafts. |
| TimeLimit | Existing values still represent seconds per question. This migration does not reinterpret them as a total exam limit. |
| Question rubric, external ID, order, active state | Retained as QUEST_ESS extensions, including QuestionData JSON. QUEST_BANK groups an exam's source questions; DocSource is nullable because an exam may use multiple EXAM_DOC sources. |
| Essential questions and changing drafts | INTERACTION stores the actual prompt and EssentialQuestion for each exchange. QuestionID links to the original professor bank question; follow-ups do not add QUEST_ESS rows. ExternalQuestionID preserves report grouping even for historical/standalone sessions without a bank question. Version 6 migrates old snapshots and follow-up concepts onto interactions and removes those duplicate bank entries after making a backup. |
| Evaluation and next action | INTERACTION.Evaluation preserves the entire model JSON; NextAction preserves the decision. The faculty transcript view renders criterion judgments, evidence, missing concepts, misconceptions, and uncertainty. Existing attainment reports remain available. |
| Session progress, retrieval evidence, next prompt | Session progress fields and INTERACTION.RetrievedJSON / NextPrompt remain to resume and audit the exam. |
| Response duration | CLIP_RESP.Duration remains as an optional extension. |
| Historical timestamps | Older AskedAt/AnsweredAt values were submission timestamps, not measured playback/response boundaries. They are retained as historical metadata/submission times; unknown question/response boundaries remain empty/NULL. Do not interpret them as measured clip boundaries. |
| Earlier local v3 fields and offsets | Unmapped original values (including old evaluation IDs, scalar grades, AskedAt, and numeric response offsets) are archived in LEGACY_ERD_FIELDS by table/row. Offsets are converted to absolute times only when the recording start is known. |
| Historical full recordings / question videos | The database cannot recover footage that was never recorded or a video association never stored. Old full-recording rows without footage are marked `unavailable_legacy`. Existing known recording paths are retained. |
| Analytics and schema history | Existing analytics tables and schema_migrations remain. |

## Recording and timeline behavior

Before the exam begins, the student grants screen **with system audio**, webcam,
and microphone access. Missing system audio prevents starting; Chrome or Edge
with the audio-sharing checkbox enabled is the intended environment. Screen
capture APIs require HTTPS or localhost. The recording composites the screen
with a webcam inset, and mixes screen audio with microphone audio into WebM.
It starts before the session-creation request, so examiner preparation and the
first question are included. These streams are retained throughout the exam,
independently of per-answer microphone recordings.

The browser uploads numbered five-second segments. Retrying an identical
segment is safe; conflicting segments are rejected. On AI completion it stops
the recorder, uploads remaining segments, verifies a contiguous sequence, and
assembles the full recording. Failed final uploads expose a retry button and
retain unsaved browser segments. Do not close the page before saving finishes.
Abrupt browser/process termination cannot guarantee the last unuploaded segment;
already uploaded parts remain on disk for recovery. Losing capture permissions
interrupts the exam and saves the footage captured so far with an interrupted
status. Keep the capture page open and active while taking the exam.

Timestamps use timezone-qualified UTC strings:

* SESSION.StartTime and RECORDING.StartTime: capture starts when the student
  begins; SESSION.EndTime: AI concludes; RECORDING.EndTime: capture stops.
* INTERACTION is created before playback. StartTime is first playback, and
  QuestionEndTime is the first completed playback. Replays do not overwrite them.
* CLIP_RESP.StartTime and EndTime mark the student's answer recorder boundaries.
* INTERACTION.EndTime marks completed evaluation/next-action determination.
* ActualQuestionTxt is the exact delivered prompt. ActualQuestionVid is a
  retained MP4 containing the generated voice and animated face, copied outside
  the regenerable media cache before playback.

CLIP_TRANS permits multiple rows per response. Only PickedTransID is joined into
evaluation/report reads, and a database trigger rejects selections from another
interaction. The current single transcript is selected automatically. Future
transcript selection must also rerun evaluation; a selection interface is not
introduced by this change.

The faculty Transcripts page provides protected playback/download access to
the full recording, per-response audio, and each retained question video, along
with essential questions and readable evaluations. Other professors and students
cannot use these audit-media endpoints.

## Verification

Run the Python suite with `python -m unittest discover -s tests -q` and the
browser-recording lifecycle test with `node tests/test_session_recording.cjs`.
Tests cover both prior schemas, migration rollback, preservation, foreign keys,
generated essential questions, selected-transcript isolation, recording retries,
missing segments, interruption, and capture permission cleanup. These use model
and device substitutes; real camera/screen permission capture still needs a
browser/device smoke test on the deployment machine.
