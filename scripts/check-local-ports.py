"""Exit 0 for free ports, 10 for this app already running, 1 for a conflict."""
import json
import socket
import sys
import urllib.request


def busy(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


occupied = [port for port in (8000, 8001) if busy(port)]
if not occupied:
    sys.exit(0)

if occupied == [8000, 8001]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=3) as response:
            student = json.load(response)
        with urllib.request.urlopen("http://127.0.0.1:8001/openapi.json", timeout=3) as response:
            faculty = json.load(response)
        paths = student.get("paths", {}).keys()
        student_app = {"/api/sessions", "/api/answers"} <= paths or {"/video", "/transcribe"} <= paths
        if student_app and faculty.get("info", {}).get("title") == "Faculty Exam Builder":
            print("The system is already running. No second instance was started.")
            print("Student: http://localhost:8000")
            print("Faculty: http://localhost:8001/login")
            print("To restart, stop the original instance first (Ctrl+C in its terminal).")
            sys.exit(10)
    except (OSError, ValueError):
        pass

print(f"Cannot start: port(s) {', '.join(map(str, occupied))} already in use.", file=sys.stderr)
print("Another instance may be starting. Stop its original terminal with Ctrl+C before retrying.", file=sys.stderr)
print("No existing process was stopped.", file=sys.stderr)
sys.exit(1)
