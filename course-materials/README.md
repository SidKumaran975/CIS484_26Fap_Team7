# Professor course-material folder

Place class files in this folder before publishing the course index. Supported
formats are PDF, PowerPoint (`.pptx`), Word (`.docx`), Markdown, and text.

Recommended organization:

```text
course-materials/
├── assessment.yaml
├── slides/
├── activities/
├── readings/
└── rubrics/
```

`assessment.yaml` is authoritative for question IDs, learning objectives, and
rubric criteria. The other documents provide evidence used by retrieval. After
adding or changing files, open `/admin` in the running application and publish
the course again.

Course files are ignored by Git except for this README, the starter assessment,
and the demonstration notes. On the Ubuntu server, set `COURSE_CONTENT_DIR` to
`/var/lib/capstone/course` and keep the professor's real materials there.

Do not place executables, archives, password-protected files, macros, or student
records in this directory. Scanned PDFs require OCR before this version can
index them.
