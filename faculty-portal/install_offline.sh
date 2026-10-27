#!/usr/bin/env bash
# Offline installer for the Faculty Exam Builder.
# Needs NO internet, NO system pip, NO python3-venv package. Only python3 (3.10, 3.11 or 3.12) on x86_64.
# Usage:  bash install_offline.sh
set -euo pipefail
cd "$(dirname "$0")"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }

# ---- 1. Check the machine matches the bundled wheels ----
ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
  red "This bundle has x86_64 wheels, but this server is $ARCH."
  red "Re-run build_bundle.sh on an internet machine with --platform for $ARCH."; exit 1
fi
command -v python3 >/dev/null || { red "python3 is not installed. Ubuntu ships it by default; check 'which python3'."; exit 1; }
PYV=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
case "$PYV" in
  3.10|3.11|3.12) green "Python $PYV on $ARCH: supported." ;;
  *) red "Python $PYV found. Bundled wheels cover 3.10, 3.11, 3.12."
     red "Re-run build_bundle.sh with your version added, on an internet machine."; exit 1 ;;
esac

TAG="cp${PYV/./}"
if ! ls wheels/*-"$TAG"-*.whl >/dev/null 2>&1; then
  red "No Python $PYV packages in ./wheels."
  red "Wheels are not stored in Git. On a machine with internet run:  PY_VERSIONS=$PYV bash build_bundle.sh"
  red "then copy the faculty-portal/wheels/ folder to this server."; exit 1
fi

# ---- 2. Create a virtual environment (works even without the python3-venv apt package) ----
if [ ! -x venv/bin/python ]; then
  python3 -m venv venv 2>/dev/null || python3 -m venv --without-pip venv
fi
PIP_WHEEL=$(ls wheels/pip-*.whl | head -1)

# ---- 3. Install from the local wheels folder only ----
# Running pip straight out of its wheel file means we never need a system pip.
venv/bin/python "$PIP_WHEEL/pip" install --no-index --find-links wheels --quiet "$PIP_WHEEL"
venv/bin/python -m pip install --no-index --find-links wheels --quiet -r requirements.txt
venv/bin/python -c "import fastapi, uvicorn, httpx, pypdf, docx, lxml, pptx, openpyxl, defusedxml, multipart" \
  && green "Python packages installed (offline)."

# ---- 4. Check Ollama ----
if command -v ollama >/dev/null; then
  if ollama list 2>/dev/null | grep -q '^llama3'; then green "Ollama has llama3."
  else red "Ollama is installed but llama3 is missing. See README → 'Getting Llama 3 onto the server'."; fi
else
  red "Ollama is not installed. See README → 'Getting Ollama onto the server'."
fi

echo
green "Done. Create the first faculty login:  ./venv/bin/python manage_users.py add <username> --role faculty"
green "Then start with:                        ./venv/bin/python app.py"
echo  "Run as a service:   see faculty-exam-builder.service"
