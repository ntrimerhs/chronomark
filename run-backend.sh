#!/usr/bin/env bash
# MSYS2 / Git Bash launcher for the backend (Windows Python venv).
#
#   ./run-backend.sh            start uvicorn on http://127.0.0.1:8000
#   ./run-backend.sh --check    print what it would use, start nothing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/venv/Scripts/python.exe"

[ -x "$PY" ] || { echo "missing $PY -- create the venv first" >&2; exit 1; }

# ffmpeg-python shells out to the ffmpeg/ffprobe binaries. MSYS2 converts PATH to
# Windows form when it spawns a native process, so the POSIX path is correct here.
export PATH="$ROOT/tools/ffmpeg:$PATH"

# Keep the embedding models in the project instead of %USERPROFILE%\.cache.
export HF_HOME="$ROOT/models"

if [ "${1:-}" = "--check" ]; then
    echo "python : $("$PY" --version 2>&1)"
    echo "ROOT   : $ROOT"
    echo "PATH[0]: $ROOT/tools/ffmpeg"
    echo "HF_HOME: $HF_HOME"
    "$PY" - <<'PYCODE'
import shutil, sys
ff = shutil.which("ffmpeg")
print("ffmpeg :", ff or "NOT FOUND")
sys.exit(0 if ff else 1)
PYCODE
    exit $?
fi

# qdrant_store.py opens ./qdrant_data relative to the working directory, so the
# server has to run from backend/.
cd "$ROOT/backend"
echo "Starting backend on http://127.0.0.1:8000 (Ctrl+C to stop)"
exec "$PY" -m uvicorn main:app --host 127.0.0.1 --port 8000
