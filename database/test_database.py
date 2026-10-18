# Tests for database.py. Run with:  python test_database.py
# Uses a separate test database, so the real exam_data.db is never touched.

import os
import database as db

db.DB_FILE = "test_exam_data.db"  # Point every function at a throwaway test database
if os.path.exists(db.DB_FILE):
    os.remove(db.DB_FILE)  # Start fresh each run so old test data doesn't pile up
db.create_tables()


# --- TEST 1: full fake exam, then read it back ---
session_id = db.start_session("Jane Doe", "CIS 304")
q1 = db.save_question("CIS 304", "What is data? What is information? What is the DIKW model?", "prof_babik")
db.save_message(session_id, "avatar", "What is data? What is information? What is the DIKW model?", question_id=q1)
db.save_message(session_id, "student", "Data are raw facts. Information is data with context.")
db.save_message(session_id, "avatar", "Can you give an example of turning data into information?")  # follow-up, no question_id
db.end_session(session_id)
transcript = db.get_transcript(session_id)
assert len(transcript) == 3, "Expected 3 messages in the transcript"
print("TEST 1 passed: exam saved and transcript read back")
for speaker, text, timestamp in transcript:
    print(f"   [{timestamp}] {speaker}: {text}")


# --- TEST 2: questions stay separated by course ---
db.save_question("CIS 304", "What is an ERP? How does it help a business organization?", "prof_babik")
db.save_question("CIS 330", "Explain how an INNER JOIN works.", "prof_smith")
cis304 = db.get_questions("CIS 304")
assert len(cis304) == 2, "CIS 304 should have exactly 2 questions"
assert all("INNER JOIN" not in text for _, text in cis304), "CIS 330 question leaked into CIS 304"
print("TEST 2 passed: get_questions only returns that course's questions")


# --- TEST 3: chunking splits long text without breaking the size limit ---
long_text = ("Enterprise architecture is a blueprint of the business. " * 60).strip()  # one huge paragraph
chunks = db.chunk_text(long_text, chunk_size=500)
assert len(chunks) > 1, "Long text should be split into several chunks"
assert all(len(c) <= 500 for c in chunks), "A chunk went over the size limit"
print(f"TEST 3 passed: long text split into {len(chunks)} chunks, all within the limit")


# --- TEST 4: upload materials for two courses; chunks don't mix ---
with open("sample_cis304.txt", "w", encoding="utf-8") as f:
    f.write("Module notes on ERP systems.\n\nERP integrates finance, HR, and sales in one database.")
with open("sample_cis330.txt", "w", encoding="utf-8") as f:
    f.write("Notes on SQL joins.\n\nAn INNER JOIN returns rows with matching values in both tables.")

doc_304 = db.save_document("CIS 304", "sample_cis304.txt", "prof_babik")
db.save_document("CIS 330", "sample_cis330.txt", "prof_smith")

assert len(db.get_documents("CIS 304")) == 1, "CIS 304 should list 1 document"
cis304_chunks = db.get_chunks("CIS 304")
assert cis304_chunks, "CIS 304 should have chunks"
assert all("INNER JOIN" not in text for _, _, text in cis304_chunks), "CIS 330 material leaked into CIS 304"
print("TEST 4 passed: materials saved, and each course only sees its own chunks")


# --- TEST 5: the stored file comes back exactly as uploaded ---
db.export_document(doc_304, "exported_copy.txt")
with open("sample_cis304.txt", "rb") as a, open("exported_copy.txt", "rb") as b:
    assert a.read() == b.read(), "Exported file doesn't match the original"
print("TEST 5 passed: file stored as a BLOB comes back byte for byte")


# --- Clean up test files ---
for path in ["sample_cis304.txt", "sample_cis330.txt", "exported_copy.txt", db.DB_FILE]:
    if os.path.exists(path):
        os.remove(path)
print("\nAll tests passed.")
