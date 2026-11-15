#!/bin/bash
# Usage: bash read.sh BOOK.pdf VOICE.wav OUT.mp3 [--pages 2-66] [other options]
# Runs voice_reader.py in the ~/my-voice Python environment.
# Set VOICE_ENV to use a different environment.
VOICE_ENV="${VOICE_ENV:-$HOME/my-voice}"
if [ -f "$VOICE_ENV/bin/activate" ]; then
  source "$VOICE_ENV/bin/activate"
fi
exec python "$(dirname "$0")/voice_reader.py" "$@"
