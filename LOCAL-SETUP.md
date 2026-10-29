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

# Updated local AI oral examination system

Updated October 29, 2026 through origin/main at 5162888 (including deployment branch 893f686), preserving Windows/WSL compatibility changes on codex/windows-exam-upgrade. Local changes are backed up in Git stashes. Question-import tests (7), database checks (5), and syntax checks passed. WSL access was denied during this update, so Linux dependency installation and full runtime verification remain pending. Install openpyxl==3.1.5 and defusedxml==0.7.1 into the main WSL environment before launching. The lockfile and real-model verification below describe the earlier October 17 installation.

## Revised ERD (schema version 2)

USER now owns first/last name and email. STUDENT and PROFESSOR tables are removed;
COURSE, SESSION, AVATAR, USER_COURSE, and USER_DEPART reference USER directly.
Each user has one avatar; replacements apply to existing exams. On the next
restart, existing version 1 databases are backed up and upgraded automatically.
See DATABASE-SCHEMA.md. This chat could not execute WSL to apply the live upgrade.

## Unified relational database (October 29)

The next normal `Start-Local.cmd` launch migrates the legacy faculty, session,
and analytics stores before starting either web service. The unified database
is `/home/logan/.local/share/ai-oral-exam/runtime/assessment.sqlite3`.
Original files remain untouched, and consistent backups plus a migration report
are stored beside the new database under `database-backups/`.
See `DATABASE-SCHEMA.md` for the ERD mapping and rollback procedure.
The source stores below describe the previous installation, not the new write paths.
WSL access was denied during implementation; the actual Linux data migration and
real-model startup check have not been performed in this chat.

## Start and stop

Double-click **Start-Local.cmd**, or run it from the project folder:

```powershell
cd "C:\Users\logan\Downloads\Project484\CIS484_26Fap_Team7"
.\Start-Local.cmd
```

This invokes the PowerShell launcher with an execution-policy override for that one process. It does not change the machine's execution policy. If your PowerShell already permits scripts, .\Start-Local.ps1 works too.

Keep the launcher window open. Press **Ctrl+C** there to stop both web services. The launcher also stops Ollama if it started that server; an independently running Ollama server is left alone. A second launch detects existing services before starting anything. Do not launch the faculty server separately: the new pipeline starts both services itself.

- Sign in: http://localhost:8001/login
- Faculty dashboard: http://localhost:8001/
- Student assessments: http://localhost:8000/
- Student health endpoint: http://localhost:8000/health

The student page now requires a **student account** and redirects unauthenticated visitors to sign-in. Faculty accounts redirect to the faculty dashboard. No permanent accounts were created during setup, following the user's earlier instruction.

To create accounts yourself, open the application Linux user from PowerShell:

```powershell
wsl -d Ubuntu-22.04 -u logan
```

Then run inside Ubuntu:

```bash
cd /mnt/c/Users/logan/Downloads/Project484/CIS484_26Fap_Team7/faculty-portal
~/.local/share/ai-oral-exam/venvs/main/bin/python manage_users.py add logan --role faculty --name 'Logan'
~/.local/share/ai-oral-exam/venvs/main/bin/python manage_users.py add student1 --role student --name 'Test Student'
```

Each command prompts for a password. These are separate account roles; use a student account to take the exam.

## New workflow

Faculty can now save a PNG photo and WAV reference voice in **Professor avatar**
on the dashboard. Each user has one avatar; replacements are used by existing and future exams.
See [PROFESSOR-MEDIA.md](PROFESSOR-MEDIA.md) for formats, storage and team update
instructions. Restart the application after updating to load the new controls
and automatic database migration.

1. Faculty creates a course and uploads files or a folder.
2. Faculty indexes that course's material. Nomic embeddings are stored in a separate local Qdrant index for each course.
3. Llama 3 generates questions; faculty reviews and publishes the exam. Publishing requires a current course index.
4. A student signs in, selects a published exam and starts a session.
5. XTTS and Wav2Lip generate that question's talking-avatar video. The student records an answer after playback.
6. Faster-Whisper transcribes the answer. Local retrieval supplies course evidence and Qwen evaluates the rubric.
7. The system asks a follow-up or advances. Session progress, responses and evaluations are saved in SQLite.
8. Faculty can inspect operational analytics.

This replaces the old standalone greeting. Startup no longer renders a greeting before serving the pages. New question/follow-up videos render on demand; cached questions reuse their media. Rendering and evaluation can still take substantial time on this 4 GB GPU. Energy analytics are estimates, not calibrated electricity measurements.

## Laptop runtime and locations

Windows 11, WSL2, Ubuntu 22.04.5, Python 3.10. NVIDIA RTX 3050 Ti Laptop GPU, 4 GB VRAM; existing Windows NVIDIA driver 617.14. No Docker installation, Linux display driver, or standalone CUDA toolkit was required.

| Item | Location / version |
| --- | --- |
| Main/STT Python | /home/logan/.local/share/ai-oral-exam/venvs/main/bin/python |
| Wav2Lip Python | /home/logan/.local/share/ai-oral-exam/venvs/wav2lip/bin/python |
| PyTorch / torchaudio | Matched 2.8.0+cu126 in both environments |
| TTS | coqui-tts 0.27.5; transformers 4.57.6 |
| Transcription | faster-whisper 1.2.1, base.en, CPU/int8 |
| Vector store | qdrant-client 1.19.1, embedded/local |
| Ollama binary | ~/.local/share/ai-oral-exam/ollama/bin/ollama, version 0.40.5 |
| Ollama models | ~/.ollama/models: llama3, qwen2.5:7b, nomic-embed-text |
| XTTS cache | ~/.local/share/tts/tts_models--multilingual--multi-dataset--xtts_v2 |
| Whisper cache | ~/.cache/huggingface/hub |
| Accounts/courses/exam-builder database | faculty-portal/exam_builder.db in this Windows checkout |
| Published exam JSON | faculty-portal/exams/ in this checkout |
| Uploaded course files | ~/.local/share/ai-oral-exam/runtime/faculty-courses/ |
| Course vector indexes | ~/.local/share/ai-oral-exam/runtime/faculty-indexes/ |
| Assessment sessions/transcripts/evaluations | ~/.local/share/ai-oral-exam/runtime/sessions.sqlite3 |
| Analytics | ~/.local/share/ai-oral-exam/runtime/analytics.sqlite3 |
| Generated question/follow-up media | ~/.local/share/ai-oral-exam/runtime/media/ |
| Service/download logs | ~/.local/share/ai-oral-exam/logs/ |

The Linux runtime locations are set by scripts/start-local.sh. They keep Qdrant locks and model/media caches on Linux storage rather than the Windows mount. The faculty database and published exams retain their original locations. Student recordings are retained after processing and linked through RESP_REC in the unified database. Faculty can play and download them from the transcript report. Old speech-to-text/recordings/ data from the previous version was preserved.

Linux home files can be reached from Windows Explorer through \\wsl.localhost\Ubuntu-22.04\home\logan\.local\share\ai-oral-exam\.

## Windows/GPU adaptations

- Start-Local.cmd avoids the script-policy error without a persistent policy change. Start-Local.ps1 explicitly selects Ubuntu-22.04 and Linux user logan; parameters can override either.
- The wrapper starts Ollama, checks all three models and required assets, then calls the new pipeline exactly once. It does not start a duplicate faculty service.
- A port preflight and file lock prevent accidental duplicate launches. The updated preflight recognizes the new assessment API.
- The pipeline cleans up both child servers on Ctrl+C or normal termination.
- Exam publication supports a configured exam-storage folder outside the source directory; an upstream relative-path error discovered by integration testing was corrected.
- One Ollama request/model is loaded at a time; models unload after use to free VRAM for XTTS/Wav2Lip. The server defaults to a 4096-token context; faculty generation uses 2048. Large models use GPU/CPU offload as needed.
- The installed PyTorch 2.8 / torchaudio 2.8 combination is retained. TorchCodec is not installed: it is not required by this Coqui/torchaudio configuration. Do not blindly apply the upstream TTS dependency file on top of these verified environments.
- Maintained coqui-tts handles checkpoint compatibility; the upstream global torch.load monkey patch and no-op audio-backend call were removed. TTS_DEVICE=cpu remains an explicit fallback.
- The original upstream Wav2Lip download is TorchScript; the loader supports it as well as legacy checkpoints.
- Avatar rendering uses resize factor 2, face batch 1, lip batch 8. Chin padding is 0 10 0 0 at that resized resolution to reduce the extra area below the detected face. Padding is part of the media cache key. The classic model still blurs the face and may show a patch boundary.
- Runtime files, private assets, databases, backups and generated media remain ignored by Git.

Direct dependency choices are in setup/requirements-main.in and setup/requirements-wav2lip.in. Exact installed versions are in their .lock.txt files. Historical root/Wav2Lip requirement files are preserved for reference, not used for this installation.

## Backup before upgrade

local-backups/20261017-before-upgrade/ contains:

- a consistent SQLite backup of exam_builder.db;
- the original avatar and supplied voice sample;
- published exam files;
- windows-setup-code.zip and local-changes.patch.

The prior local code changes are also preserved in a named Git stash: 'Windows local setup before deployment-branch upgrade 2026-10-17'. The old local main branch was retained. Backups include private assets and must not be committed or uploaded. Preserve the current database and runtime data before any rollback.

## Reproduce on another Windows laptop

1. With administrator approval, install Microsoft WSL and Ubuntu 22.04. Restart if Windows requests it. Initialize a regular Linux user.
2. Install these Ubuntu packages as root: python3-venv, python3-dev, build-essential, ffmpeg, libsndfile1, curl, ca-certificates and zstd. Use the Windows NVIDIA driver through WSL; do not install a Linux display driver.
3. Copy/clone this adapted version and enter its repository folder as the regular Linux user. Run `bash scripts/setup-python.sh`. This uses the exact lockfiles and official CUDA PyTorch wheels.
4. Run `bash scripts/install-ollama.sh` for the pinned official user-local Ollama release. The script verifies the recorded archive hash.
5. Supply authorized BabAvatar.png and text-to-speech-model/Sid.wav locally. Run `bash scripts/download-assets.sh` for the original project's linked Wav2Lip/S3FD files. After accepting XTTS-v2's model terms, run `COQUI_TOS_AGREED=1 bash scripts/download-xtts.sh`.
6. Start Ollama with `OLLAMA_KEEP_ALIVE=0 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 OLLAMA_NO_CLOUD=1 OLLAMA_CONTEXT_LENGTH=4096 ~/.local/share/ai-oral-exam/ollama/bin/ollama serve`. In another Linux terminal use that binary to pull llama3, qwen2.5:7b and nomic-embed-text. Stop this manual server before testing launcher-managed startup.
7. Change the PowerShell launcher's LinuxUser parameter if the new user's name is different. Launch Start-Local.cmd, create faculty/student accounts and follow the workflow above.

The additional models used about 5 GB of downloads during this upgrade, beyond the previous environment/model installation. Model weights and voice recordings are not in Git. Existing noncommercial XTTS acceptance from this machine was retained; another user must accept applicable model terms themselves. Wav2Lip's pretrained models are limited to personal/research/academic/noncommercial use by upstream.

## Verification

- Eight upstream unit tests passed, covering Qdrant indexing, rubric conversion, sessions, follow-up/advance rules, analytics and media caching.
- Upgraded main environment: pip check passed. Existing matched CUDA PyTorch/torchaudio and Wav2Lip environment retained.
- Both new Ollama models downloaded successfully.
- Start-Local.cmd successfully started both services; Windows localhost health/login checks passed. A duplicate launch exited cleanly without starting another instance. Graceful shutdown stopped both services and launcher-managed Ollama. Setup left the services stopped; launch them when needed. The preserved faculty database still contains zero accounts.
- Real-model end-to-end integration passed with disposable accounts/databases and ports 8010/8011: course upload/indexing, Llama question generation, exam publication, student sign-in, actual avatar rendering, Whisper transcription, Qwen evaluation, follow-up rendering, completion and analytics. The test recorded clarify then move_on, two persisted answer turns, and seven analytics runs.
- On this laptop, the first question video request took 231 seconds; the same cached question took 1.7 seconds. The first answer evaluation plus follow-up video took 324 seconds, and the final answer took 59 seconds. These are measured examples, not response-time guarantees.
- Model registry digests and sizes are recorded in setup/model-inventory.json; integration results are in setup/logs/upgrade-integration-result.json.

To repeat checks inside Ubuntu from the repository:

```bash
P=$HOME/.local/share/ai-oral-exam/venvs/main/bin/python
W=$HOME/.local/share/ai-oral-exam/venvs/wav2lip/bin/python
"$P" -m unittest discover -s tests -v
"$P" scripts/verify-local.py gpu
"$W" scripts/verify-local.py wav2lip
"$P" scripts/verify-local.py running
"$P" scripts/verify-upgrade.py
```

The running check requires the normal services. The full integration check needs Ollama and uses independent test ports; avoid simultaneous production inference on this 4 GB GPU. Test logs/results are under setup/logs/ and ignored by Git. Temporary credentials are generated only in memory and discarded; no permanent accounts are seeded by tests. Physical microphone permission/capture and speaker output remain manual browser checks.


## Account names and student answer audio

`--name "John Smith"` stores FirstName=John and LastName=Smith. Full names entered
through --first-name are also split if no surname was provided. Startup repairs
existing missing surnames from the stored full name without replacing a surname
that was explicitly saved.

Student audio is always retained. The old RETAIN_AUDIO switch has been removed.
On this laptop files remain in
`/home/logan/.local/share/ai-oral-exam/runtime/recordings/`; RESP_REC records each
successfully submitted answer's path and format. The faculty transcript report
offers playback and download through an authenticated course-owner endpoint.
Previously deleted audio cannot be recreated from its transcript.
Restart both services to load these changes.
