# Offline premade-question import checklist

This feature imports faculty-authored `.docx`, `.xlsx`, and `.csv` question
lists into the normal exam-draft workflow. It does not call an LLM while
parsing the file.

## Required Python packages

| Package | Purpose |
|---|---|
| `python-docx==1.2.0` | Opens DOCX packages and exposes paragraphs and tables |
| `lxml==6.1.3` | XML engine used by `python-docx` |
| `openpyxl==3.1.5` | Reads XLSX worksheets and cells |
| `et_xmlfile==2.0.0` | XML dependency used by `openpyxl` |
| `defusedxml==0.7.1` | Safer XML parsing support |
| `python-multipart==0.0.32` | Lets FastAPI receive the browser file upload |
| `typing_extensions==4.16.0` | `python-docx` compatibility dependency |

`csv`, `io`, `re`, `uuid`, `zipfile`, and `pathlib` are part of Python and do not
need separate downloads. Microsoft Word, LibreOffice, Java, and Pandoc are not
required. Legacy `.doc` and `.xls` files are not supported; save them as
`.docx` or `.xlsx`.

## Before the server is disconnected

The target in `deployment/README.md` is Ubuntu 22.04, x86-64, Python 3.10.
On an internet-connected machine, from `faculty-portal/`, run:

```bash
PY_VERSIONS=3.10 ARCH=x86_64 bash build_bundle.sh
```

Copy the entire repository/source update and the ignored
`faculty-portal/wheels/` directory to the server. Git does not transfer the
wheel directory because it is intentionally ignored.

## Install on the air-gapped server

If the full deployment installer has already created `.venv-stt`, install or
verify the import packages in that environment without contacting PyPI:

```bash
cd /opt/capstone
.venv-stt/bin/python -m pip install --no-index \
  --find-links faculty-portal/wheels \
  python-docx==1.2.0 lxml==6.1.3 \
  openpyxl==3.1.5 et_xmlfile==2.0.0 defusedxml==0.7.1 \
  python-multipart==0.0.32
```

For a standalone faculty-portal installation instead:

```bash
cd /opt/capstone/faculty-portal
bash install_offline.sh
```

## Test before moving the server

Test the Sprint 1 document directly:

```bash
cd /opt/capstone
.venv-stt/bin/python Parser "Question List.docx"
```

Then run the deployment checks and restart the service:

```bash
sudo -u capstone /opt/capstone/deployment/verify.sh
sudo systemctl restart capstone
sudo journalctl -u capstone -n 100 --no-pager
```

In the browser, sign in as faculty, create/open a course, start a new exam, and
choose **Import Premade Questions**. The questions should appear in the
review section. Add or verify key points, approve them, and publish.

Publishing still requires an indexed course-material collection because the
student-answer evaluator retrieves course evidence from Qdrant. Importing and
editing a draft does not require Ollama or Qdrant.

## Supported layouts

- One question per paragraph, as in `Question List.docx`.
- Numbered or labelled prompts such as `1.`, `Q1:`, or `Question 1:`.
- A question followed by `Key points:` and `Follow-up:` paragraphs.
- A table with a `Question` column and optional `Key Points`, `Answer`,
  `Rubric`, and `Follow-up` columns.
- An XLSX workbook with a `Questions` sheet, or the first visible sheet, using
  `Question`, `Key Points`, and `Follow-up` columns.
- A UTF-8 CSV file using the same three columns.

The import limit is 20 questions and 25 MB per file. Formulas are rejected;
question fields must contain plain text. Imported questions
are saved as a draft in `faculty-portal/exam_builder.db`; publishing also writes
the finalized exam JSON used by the student service.
