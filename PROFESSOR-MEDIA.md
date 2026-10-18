# Professor photos and voices

Sign in as faculty and open **Professor avatar** on the dashboard. Upload both a
front-facing PNG photo and a WAV recording, then select **Save photo and voice**.
The saved photo and audio can be previewed there. Students cannot upload or
preview these source files. Use media you have permission to use.

PNG: one static image, 256–4096 pixels in each dimension, up to 10 MB.
WAV: uncompressed 16-bit PCM, mono or stereo, 16–48 kHz, 6–30 seconds, up to 6 MB.
Use clear speech without background music. Validation checks format, not whether
the face is suitable for lip sync or the recording is good for voice cloning.

## What happens when publishing

Publishing records the faculty account ID and the currently saved media version
in the database and published exam JSON. Question and follow-up generation use
that pair. Content versions are immutable, so replacing profile media affects
future publications; existing exams retain their previous pair. To update an
existing exam, publish it again. Avoid republishing while students are taking it.

Accounts without uploads and older published exams continue using the shared
BabAvatar.png and Sid.wav. An exam explicitly assigned personal media reports an
error if those files go missing; it does not silently use another voice.

The cache includes the selected assets, keeping different professors' videos
separate. A saved profile is not a rendered preview: the first question still
needs time for XTTS and Wav2Lip to generate its video.

## Updating an existing installation

1. Stop the application and back up exam_builder.db and the published exams.
2. Apply/pull the code changes. Existing environments already include Pillow and
   multipart upload support; no new models or packages are required.
3. Set FACULTY_MEDIA_STORAGE to a persistent directory writable by both services.
   Both processes must use the same value. Without a setting it defaults to
   runtime/faculty-media in the checkout. The Windows launcher selects
   ~/.local/share/ai-oral-exam/runtime/faculty-media. Compose uses its existing
   /data volume; the Ubuntu environment example uses /var/lib/capstone.
   For an existing Ubuntu service, add the new variable to its installed env file.
4. Restart normally. The faculty service automatically creates professor_media
   and adds nullable professor_id/media_version columns to exams. No existing
   rows are removed. Restarting again is safe. No accounts are created.

Back up this media directory together with the database and exam JSON. Versions
used by published exams must remain available. Old versions are deliberately
retained; this feature does not implement automatic cleanup or profile deletion.
The media directory is private runtime data, not a static web directory. The
default directory is Git-ignored. Never commit uploads or a production database.

## Review and verification

Feature code: faculty-portal/app.py and index.html, rag/profiles.py, rag/media.py,
rag/faculty.py, speech-to-text/app.py and text-to-speech-model/run_voice.py.
Deployment changes are one storage setting per launcher/environment.

Run with the configured main Python environment:

```bash
python -m unittest discover -s tests -v
```

Tests use temporary databases and files. They cover faculty/student authorization,
invalid uploads and size limits, private previews, exam ownership and media
snapshots, replacement and republishing, legacy fallback, cache separation and
the TTS/Wav2Lip command arguments. Existing assessment tests are included.

The feature-only patch prepared for this change was checked against deployment
branch commit a3aeefc and passed all 11 tests in a temporary upstream checkout.
It also includes the small publication-path fix for exam directories outside the
source folder. It excludes this laptop's other Windows/GPU setup modifications.
On another checkout of that version, apply the supplied patch with:

```bash
git apply --check /path/to/professor-media-feature.patch
git apply /path/to/professor-media-feature.patch
```

Review and commit the changes on a feature branch, then push/open a pull request
through the team's normal GitHub workflow. A different upstream version may need
conflict resolution. Do not apply this patch again to this already-updated laptop.
