"""Instructor review of exam sessions (no internet, no extra packages).

    python review.py list                      # all sessions and their status
    python review.py approve 3 --by "Dr. Lee"  # ID and face match
    python review.py reject 3 --by "Dr. Lee" --note "Face does not match ID"

Open the photos in the photos/ folder (file names are shown by `list`),
compare the ID card with the face photo, then approve or reject.
Uses the same EXAM_DB setting as app.py.
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("EXAM_DB", os.path.join(BASE_DIR, "exam.db"))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("approve", "reject"):
        s = sub.add_parser(name)
        s.add_argument("session_id", type=int)
        s.add_argument("--by", required=True, help="your name, recorded on the report")
        s.add_argument("--note", default="")
    args = p.parse_args()

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cols = {r[1] for r in db.execute("PRAGMA table_info(exam_sessions)")}
    if "verification_status" not in cols:
        sys.exit("Run app.py once first so the database is upgraded.")

    if args.cmd == "list":
        rows = db.execute("SELECT * FROM exam_sessions ORDER BY id").fetchall()
        for r in rows:
            print(f"#{r['id']} student {r['student_id']}  status={r['verification_status']}  "
                  f"started={r['started_at']}  ended={r['ended_at'] or '-'}\n"
                  f"     id photo:   {r['id_photo_path'] or '-'}\n"
                  f"     face photo: {r['photo_path'] or '-'}")
        if not rows:
            print("No sessions yet.")
        return

    status = "approved" if args.cmd == "approve" else "rejected"
    row = db.execute("SELECT notes FROM exam_sessions WHERE id = ?",
                     (args.session_id,)).fetchone()
    if row is None:
        sys.exit(f"No session #{args.session_id}.")
    notes = row["notes"] or ""
    if args.note:
        notes = (notes + "\n" if notes else "") + f"[review] {args.note}"
    db.execute("UPDATE exam_sessions SET verification_status = ?, reviewed_by = ?, "
               "reviewed_at = ?, notes = ? WHERE id = ?",
               (status, args.by, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes, args.session_id))
    db.commit()
    print(f"Session #{args.session_id} marked {status}.")


if __name__ == "__main__":
    main()
