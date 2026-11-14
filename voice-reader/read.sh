#!/usr/bin/env bash
# read.sh: run voice_reader.py with a Python that has Chatterbox.
#   bash read.sh BOOK.pdf REF.wav OUT.mp3 --pages 2-66 --expression 0.6 --pace 0.5
# First run without Chatterbox installed: makes .venv here and installs it (a few GB).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

has_chatterbox() { "$1" -c "import chatterbox, pymupdf" >/dev/null 2>&1; }

py=""
for cand in "$here/.venv/bin/python" "$here/venv/bin/python" "$here/env/bin/python" python3; do
  if command -v "$cand" >/dev/null 2>&1 && has_chatterbox "$cand"; then py="$cand"; break; fi
done
# An existing env with Chatterbox but not PyMuPDF: add PyMuPDF to it.
if [ -z "$py" ]; then
  for cand in "$here/.venv/bin/python" "$here/venv/bin/python" "$here/env/bin/python"; do
    if [ -x "$cand" ] && "$cand" -c "import chatterbox" >/dev/null 2>&1; then
      "$cand" -m pip install -q pymupdf && py="$cand" && break
    fi
  done
fi
if [ -z "$py" ]; then
  base=""
  for v in python3.11 python3.12 python3.10 python3; do
    command -v "$v" >/dev/null 2>&1 && { base="$v"; break; }
  done
  [ -n "$base" ] || { echo "Python 3 isn't installed. Run: brew install python@3.11"; exit 1; }
  echo "Setting up Chatterbox in $here/.venv (one time, needs a few GB)…"
  "$base" -m venv "$here/.venv"
  "$here/.venv/bin/python" -m pip install -q --upgrade pip
  "$here/.venv/bin/python" -m pip install -q -r "$here/requirements.txt"
  py="$here/.venv/bin/python"
fi

exec "$py" "$here/voice_reader.py" "$@"
