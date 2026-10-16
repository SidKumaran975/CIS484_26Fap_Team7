#!/usr/bin/env python3
"""
Create and manage portal accounts. Run from the faculty-portal folder.

  python manage_users.py add jsmith --role faculty --name "Dr. Jane Smith"
  python manage_users.py add dukesd --role student --name "Dana Duke"
  python manage_users.py import roster.csv           # bulk-create students
  python manage_users.py passwd jsmith
  python manage_users.py remove dukesd
  python manage_users.py list

roster.csv needs a header row:  username,name[,password]
Rows without a password get a random one, and every new login is written to
credentials_<timestamp>.csv so you can hand them out. That file holds
plaintext passwords: give them out, then delete it. It is git-ignored.
"""

import argparse
import csv
import getpass
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

import auth

ALPHABET = string.ascii_letters + string.digits
ALPHABET = "".join(ch for ch in ALPHABET if ch not in "0O1lI")   # nothing easy to misread


def random_password(n: int = 12) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def ask_password() -> str:
    while True:
        p1 = getpass.getpass("Password: ")
        if len(p1) < auth.MIN_PASSWORD:
            print(f"  At least {auth.MIN_PASSWORD} characters.")
            continue
        if getpass.getpass("Repeat password: ") == p1:
            return p1
        print("  Passwords didn't match.")


def cmd_add(a):
    password = a.password or (random_password() if a.generate else ask_password())
    auth.create_user(a.username, a.name or a.username, a.role, password)
    print(f"Created {a.role} '{auth.normalize(a.username)}'.")
    if a.generate:
        print(f"Generated password: {password}")


def cmd_import(a):
    path = Path(a.csv)
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows or "username" not in rows[0]:
        sys.exit("CSV needs a header row with at least: username,name")
    created, skipped = [], []
    for row in rows:
        username = (row.get("username") or "").strip()
        if not username:
            continue
        password = (row.get("password") or "").strip() or random_password()
        try:
            auth.create_user(username, (row.get("name") or "").strip(), a.role, password)
            created.append((auth.normalize(username), (row.get("name") or "").strip(), password))
        except ValueError as e:
            skipped.append(f"{username}: {e}")
    if created:
        out = Path(f"credentials_{datetime.now():%Y%m%d_%H%M%S}.csv")
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["username", "name", "password"])
            w.writerows(created)
        print(f"Created {len(created)} {a.role} account(s). Logins written to {out}")
        print("That file has plaintext passwords. Hand them out, then delete it.")
    for s in skipped:
        print("  skipped", s)


def cmd_passwd(a):
    password = random_password() if a.generate else ask_password()
    auth.set_password(a.username, password)
    print(f"Password changed for '{auth.normalize(a.username)}'. Their existing sessions were signed out.")
    if a.generate:
        print(f"Generated password: {password}")


def cmd_remove(a):
    auth.delete_user(a.username)
    print(f"Removed '{auth.normalize(a.username)}'.")


def cmd_list(a):
    users = auth.list_users()
    if not users:
        print("No accounts yet.")
    for u in users:
        print(f"{u['role']:<8} {u['username']:<20} {u['display_name']}")


def main():
    p = argparse.ArgumentParser(description="Manage faculty and student logins.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="create one account")
    s.add_argument("username")
    s.add_argument("--role", choices=auth.ROLES, required=True)
    s.add_argument("--name", help="display name")
    s.add_argument("--password", help="avoid on shared machines: it lands in shell history")
    s.add_argument("--generate", action="store_true", help="generate a random password and print it")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("import", help="bulk-create accounts from a CSV")
    s.add_argument("csv")
    s.add_argument("--role", choices=auth.ROLES, default="student")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("passwd", help="reset a password")
    s.add_argument("username")
    s.add_argument("--generate", action="store_true")
    s.set_defaults(fn=cmd_passwd)

    s = sub.add_parser("remove", help="delete an account")
    s.add_argument("username")
    s.set_defaults(fn=cmd_remove)

    sub.add_parser("list", help="list accounts").set_defaults(fn=cmd_list)

    a = p.parse_args()
    try:
        a.fn(a)
    except ValueError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
