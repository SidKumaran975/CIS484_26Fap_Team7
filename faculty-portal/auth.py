"""
Login, accounts and sessions for the faculty portal.

Standard library only (hashlib.scrypt, secrets, hmac), so nothing new to bundle
for the air-gapped server.

- One login page for everyone. The ACCOUNT decides the role, not a dropdown,
  so a student can't "pick faculty" and get in.
- Passwords: scrypt with a per-user random salt. Plaintext is never stored.
- Sessions: random token in an HttpOnly, SameSite=Strict cookie. Only a SHA-256
  of the token is stored, so a stolen database can't be replayed as a login.
- Brute force: 5 failed attempts locks that username for 5 minutes.
- Accounts are created with manage_users.py. There is no self sign-up.
"""

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent)) if str(BASE_DIR.parent) not in sys.path else None
from rag.database import database_path, initialize_database, connect
DB_PATH = database_path()

SESSION_COOKIE = "examportal_session"
SESSION_HOURS = float(os.getenv("SESSION_HOURS", "8"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"   # set 1 once the server is behind HTTPS
STUDENT_URL = os.getenv("STUDENT_URL", "")               # empty = same host, port STUDENT_PORT
STUDENT_PORT = int(os.getenv("STUDENT_PORT", "8000"))    # speech-to-text/app.py
MAX_FAILS, LOCK_SECONDS = 5, 300
MIN_PASSWORD = 8
ROLES = ("faculty", "student")

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


# ================= DATABASE =================
def _db():
    return connect(DB_PATH)


def init_auth_db():
    initialize_database(DB_PATH)

init_auth_db()


# ================= PASSWORDS =================
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        test = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                              n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(test, base64.b64decode(dk))
    except Exception:
        return False


# Used when the username doesn't exist, so a wrong username takes as long as a
# wrong password. Otherwise response time reveals which usernames are real.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


# ================= USERS (used by manage_users.py) =================
def normalize(username: str) -> str:
    return username.strip().lower()


def create_user(username: str, display_name: str, role: str, password: str, *,
                first_name: str = "", last_name: str = "", email: str = "") -> None:
    username = normalize(username)
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if not username or not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise ValueError("username may only contain letters, numbers, '.', '_' and '-'")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    first_name, last_name, email = first_name.strip(), last_name.strip(), email.strip()
    full_name = ' '.join(display_name.split())
    # Accept a full name through either the legacy --name input or a first-name
    # input with the surname omitted. Explicit separate surnames take priority.
    if not last_name and len(first_name.split()) > 1:
        first_name, last_name = first_name.split(maxsplit=1)
    elif not last_name and full_name and full_name != username:
        parts = full_name.split(maxsplit=1)
        if not first_name:
            first_name = parts[0]
        if len(parts) == 2 and first_name == parts[0]:
            last_name = parts[1]
    display_name = ' '.join(part for part in (first_name,last_name) if part) or display_name.strip() or username
    with _db() as c:
        try:
            c.execute("INSERT INTO users (username, display_name, role, pw_hash, created_at) VALUES (?,?,?,?,?)",
                      (username, display_name.strip() or username, role, hash_password(password),
                       datetime.now(timezone.utc).isoformat()))
            c.execute('UPDATE "USER" SET FirstName=?,LastName=?,Email=? WHERE UserName=?',
                      (first_name or None,last_name or None,email or None,username))
        except sqlite3.IntegrityError:
            raise ValueError(f"user '{username}' already exists")


def set_password(username: str, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    with _db() as c:
        if not c.execute("SELECT id FROM users WHERE username=?", (normalize(username),)).fetchone():
            raise ValueError(f"no user '{username}'")
        c.execute("UPDATE users SET pw_hash=? WHERE username=?", (hash_password(password), normalize(username)))
        # A password change signs that user out everywhere.
        c.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=?)", (normalize(username),))


def delete_user(username: str) -> None:
    with _db() as c:
        row = c.execute("SELECT id FROM users WHERE username=?", (normalize(username),)).fetchone()
        if not row:
            raise ValueError(f"no user '{username}'")
        c.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        c.execute("DELETE FROM users WHERE id=?", (row["id"],))


def list_users() -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute(
            "SELECT username, display_name, role, created_at FROM users ORDER BY role, username")]


def count_faculty() -> int:
    with _db() as c:
        return c.execute("SELECT COUNT(*) FROM users WHERE role='faculty'").fetchone()[0]


# ================= SESSIONS =================
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with _db() as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))   # housekeeping
        c.execute("INSERT INTO sessions VALUES (?,?,?)",
                  (_token_hash(token), user_id, time.time() + SESSION_HOURS * 3600))
    return token


def current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with _db() as c:
        row = c.execute("""SELECT u.id, u.username, u.display_name, u.role, s.expires_at
                           FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?""",
                        (_token_hash(token),)).fetchone()
    if not row or row["expires_at"] < time.time():
        return None
    return {k: row[k] for k in ("id", "username", "display_name", "role")}


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Not signed in.")
    return user


def require_faculty(user: dict = Depends(require_user)) -> dict:
    if user["role"] != "faculty":
        raise HTTPException(403, "Faculty only.")
    return user


def student_url(request: Request) -> str:
    """Where students go after signing in: the speech-to-text exam page."""
    if STUDENT_URL:
        return STUDENT_URL
    return f"{request.url.scheme}://{request.url.hostname}:{STUDENT_PORT}/"


def home_for(user: dict, request: Request) -> str:
    return "/" if user["role"] == "faculty" else student_url(request)


# ================= LOCKOUT =================
_fails: dict[str, list] = {}   # username -> [count, locked_until]. In memory; resets on restart.


def _locked(username: str) -> bool:
    entry = _fails.get(username)
    return bool(entry and entry[1] > time.time())


def _record_fail(username: str) -> None:
    entry = _fails.setdefault(username, [0, 0.0])
    entry[0] += 1
    if entry[0] >= MAX_FAILS:
        entry[1] = time.time() + LOCK_SECONDS
        entry[0] = 0


# ================= ROUTES =================
router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/login")
def login(body: LoginRequest, request: Request, response: Response):
    username = normalize(body.username)
    if _locked(username):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    with _db() as c:
        row = c.execute("SELECT id, display_name, role, pw_hash FROM users WHERE username=?",
                        (username,)).fetchone()
    ok = verify_password(body.password, row["pw_hash"] if row else _DUMMY_HASH) and row is not None
    if not ok:
        _record_fail(username)
        # Same message whether the username or the password was wrong.
        raise HTTPException(401, "Incorrect username or password.")
    _fails.pop(username, None)
    response.set_cookie(SESSION_COOKIE, _new_session(row["id"]), max_age=int(SESSION_HOURS * 3600),
                        httponly=True, samesite="strict", secure=COOKIE_SECURE, path="/")
    user = {"username": username, "display_name": row["display_name"], "role": row["role"]}
    return {**user, "redirect": home_for(user, request)}


@router.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with _db() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
def me(request: Request, user: dict = Depends(require_user)):
    return {"username": user["username"], "display_name": user["display_name"],
            "role": user["role"], "home": home_for(user, request)}
