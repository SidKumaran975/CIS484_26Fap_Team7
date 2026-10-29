"""Real-model upgrade test using temporary accounts, data, and ports 8010/8011."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
WAV_PYTHON = Path.home() / ".local/share/ai-oral-exam/venvs/wav2lip/bin/python"
FACULTY = "http://127.0.0.1:8011"
STUDENT = "http://127.0.0.1:8010"
LOGS = ROOT / "setup/logs"
LOGS.mkdir(exist_ok=True, parents=True)


def request(client, method, url, **kwargs):
    start = time.monotonic()
    print(f"Testing {method} {url}", flush=True)
    response = client.request(method, url, **kwargs)
    assert response.status_code == 200, f"{url}: {response.status_code} {response.text[:2000]}"
    print(f"PASS ({time.monotonic() - start:.1f}s)", flush=True)
    return response


def main():
    with tempfile.TemporaryDirectory(prefix="oral-exam-upgrade-") as directory:
        temp = Path(directory)
        env = {
            **os.environ,
            "MAIN_PYTHON": str(PYTHON), "STT_PYTHON": str(PYTHON),
            "WAV2LIP_PYTHON": str(WAV_PYTHON), "STT_PORT": "8010", "STUDENT_PORT": "8010", "PORT": "8011",
            "APP_DB_PATH": str(temp / "assessment.sqlite3"),
            "DB_PATH": str(temp / "assessment.sqlite3"), "FACULTY_DB_PATH": str(temp / "faculty.db"),
            "FACULTY_EXAMS_DIR": str(temp / "exams"),
            "FACULTY_COURSE_STORAGE": str(temp / "courses"),
            "FACULTY_INDEX_STORAGE": str(temp / "indexes"),
            "SESSION_DB_PATH": str(temp / "sessions.db"),
            "ANALYTICS_DB_PATH": str(temp / "analytics.db"),
            "MEDIA_DIR": str(temp / "media"), "RECORDINGS_DIR": str(temp / "recordings"),
            "OLLAMA_HOST": "http://127.0.0.1:11434", "OLLAMA_URL": "http://127.0.0.1:11434",
            "OLLAMA_MODEL": "llama3", "EVALUATION_MODEL": "qwen2.5:7b",
            "RAG_EMBED_MODEL": "nomic-embed-text", "NUM_CTX": "2048", "LLM_TIMEOUT": "900",
            "MEDIA_MODE": "avatar", "MEDIA_GENERATION_TIMEOUT": "900", "OMP_NUM_THREADS": "4",
            "WAV2LIP_RESIZE_FACTOR": "2", "WAV2LIP_PADS": "0 10 0 0",
            "FACE_DET_BATCH_SIZE": "1", "WAV2LIP_BATCH_SIZE": "8", "MAX_FOLLOW_UPS": "1",
        }
        password = secrets.token_urlsafe(24)
        seed = 'import auth,json,sys; p=json.load(sys.stdin)["password"]; auth.create_user("setupfaculty","Setup Faculty","faculty",p); auth.create_user("setupstudent","Setup Student","student",p)'
        subprocess.run([str(PYTHON), "-c", seed], cwd=ROOT / "faculty-portal", env=env,
                       input=json.dumps({"password": password}), text=True, check=True)
        log_path = LOGS / "upgrade-integration.log"
        result = {}
        with log_path.open("w") as log:
            pipeline = subprocess.Popen([str(PYTHON), "-u", str(ROOT / "pipeline.py")],
                                        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                with httpx.Client(timeout=1200) as faculty, httpx.Client(timeout=1200) as student:
                    for attempt in range(180):
                        if pipeline.poll() is not None:
                            raise RuntimeError(f"Test services exited; see {log_path}")
                        try:
                            if faculty.get(FACULTY + "/login", timeout=2).status_code == 200 and student.get(STUDENT + "/health", timeout=2).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(1)
                    else:
                        raise RuntimeError(f"Services not ready; see {log_path}")
                    assert student.get(STUDENT + "/api/exams").status_code == 401
                    request(faculty, "POST", FACULTY + "/api/login", json={"username": "setupfaculty", "password": password})
                    course = request(faculty, "POST", FACULTY + "/api/courses", json={"code": "SETUP101", "name": "Computer Networks"}).json()
                    cid = course["id"]
                    material = ("TCP provides reliable ordered delivery using acknowledgments and retransmissions. "
                                "UDP sends independent datagrams without guaranteed delivery or ordering. "
                                "TCP suits file transfers. UDP suits latency-sensitive real-time applications. ") * 3
                    request(faculty, "POST", FACULTY + f"/api/courses/{cid}/materials",
                            files={"file": ("networks.txt", material.encode(), "text/plain")},
                            data={"relative_path": "lecture-notes/networks.txt"})
                    index = request(faculty, "POST", FACULTY + f"/api/courses/{cid}/index").json()
                    assert index["ready"] and index["chunk_count"] > 0
                    draft = request(faculty, "POST", FACULTY + "/api/exams/generate", json={"course_id": cid, "num_questions": 1, "include_follow_ups": False}).json()
                    eid = draft["exam_id"]
                    request(faculty, "POST", FACULTY + f"/api/exams/{eid}/publish", json={"course_id": cid, "num_questions": 1, "questions": draft["questions"], "include_follow_ups": False})
                    request(student, "POST", FACULTY + "/api/login", json={"username": "setupstudent", "password": password})
                    page = request(student, "GET", STUDENT + "/")
                    assert "<html" in page.text.lower()
                    assert student.get(FACULTY + "/api/courses").status_code == 403
                    exam = request(student, "GET", FACULTY + f"/api/exams/{eid}").json()
                    assert "key_points" not in exam["questions"][0]
                    assert request(student, "GET", STUDENT + "/api/exams").json()["exams"]
                    session = request(student, "POST", STUDENT + "/api/sessions", json={"exam_id": eid}).json()
                    assert session["media_url"].endswith(".mp4")
                    media = request(student, "GET", STUDENT + session["media_url"])
                    assert media.headers["content-type"] == "video/mp4" and len(media.content) > 1000
                    # A second session for the same question should reuse generated media.
                    cached = request(student, "POST", STUDENT + "/api/sessions", json={"exam_id": eid}).json()
                    assert cached["media_url"] == session["media_url"]
                    answer = temp / "answer.webm"
                    subprocess.run(["ffmpeg", "-v", "error", "-i", str(ROOT / "text-to-speech-model/Sid.wav"),
                                    "-c:a", "libopus", str(answer)], check=True)
                    turns = []
                    for number in range(2):
                        with answer.open("rb") as source:
                            turn = request(student, "POST", STUDENT + "/api/answers",
                                           files={"audio": ("answer.webm", source, "audio/webm")},
                                           data={"session_id": session["session_id"]}).json()
                        assert turn["transcript"].strip() and turn["evaluation"]["criterion_results"]
                        turns.append(turn)
                        if turn["completed"]:
                            break
                        assert turn["action"] in {"probe", "clarify", "deepen"}
                        assert turn["media_url"].endswith(".mp4")
                        request(student, "GET", STUDENT + turn["media_url"])
                    assert len(turns) == 2 and turns[-1]["completed"]
                    assert turns[-1]["action"] == "move_on" and turns[-1]["media_url"] is None
                    analytics = request(faculty, "GET", FACULTY + "/api/analytics/summary").json()
                    assert analytics["run_count"] >= 6 and analytics["input_tokens"] > 0
                    with sqlite3.connect(temp / "assessment.sqlite3") as db:
                        assert db.execute("select count(*) from assessment_turns where session_id=?", (session["session_id"],)).fetchone()[0] == 2
                    result = {"passed": True, "question": draft["questions"][0]["question"],
                              "actions": [turn["action"] for turn in turns], "analytics_runs": analytics["run_count"],
                              "media_bytes": len(media.content), "temporary_accounts_only": True}
            finally:
                pipeline.terminate()
                try:
                    pipeline.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pipeline.kill()
                    pipeline.wait()
        (LOGS / "upgrade-integration-result.json").write_text(json.dumps(result, indent=2))
        print("PASS: real-model faculty publishing -> course retrieval -> question video -> WebM answer -> rubric evaluation -> follow-up video -> completion -> analytics", flush=True)
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
