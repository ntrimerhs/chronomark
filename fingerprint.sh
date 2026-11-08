#!/usr/bin/env bash
# Prints one fingerprint for "are we running the same thing?"
#
#   ./fingerprint.sh            full report + a single FINGERPRINT line
#   ./fingerprint.sh --short    only the fingerprint line
#
# Compare the FINGERPRINT line between two machines. It covers the committed
# tree, any uncommitted edits, the dependency locks and the model revisions --
# i.e. everything that decides behaviour -- so a matching line means the two
# checkouts are equivalent.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

SHORT=0
[ "${1:-}" = "--short" ] && SHORT=1

# --- repository -----------------------------------------------------------
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo 'no-git')"
TREE="$(git rev-parse 'HEAD^{tree}' 2>/dev/null || echo 'no-git')"
# Paths + modes + blob ids, which git normalises (LF in the index regardless of
# CRLF on disk), so this hash is stable across Windows/MSYS2/WSL checkouts.
TRACKED="$(git ls-files -s | sort | sha256sum | cut -d' ' -f1)"
DIRTY_COUNT="$(git status --porcelain=v1 --untracked-files=no | wc -l | tr -d ' ')"
DIRTY="$(git status --porcelain=v1 --untracked-files=no | sort | sha256sum | cut -d' ' -f1)"

# --- installed dependencies ----------------------------------------------
hash_file() { [ -f "$1" ] && sha256sum "$1" | cut -d' ' -f1 || echo 'missing'; }

LOCK="$(hash_file frontend/package-lock.json)"

PY="$ROOT/venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/venv/bin/python"
if [ -x "$PY" ]; then
    DEPS="$("$PY" -m pip freeze 2>/dev/null | sort | sha256sum | cut -d' ' -f1)"
    PYVER="$("$PY" --version 2>&1)"
else
    DEPS="no-venv"
    PYVER="no-venv"
fi

if [ -d models/hub ]; then
    MODELS="$(ls -1d models/hub/*/refs/main 2>/dev/null | xargs -r cat 2>/dev/null | sha256sum | cut -d' ' -f1)"
else
    MODELS="no-models"
fi

FFMPEG="$("$ROOT/tools/ffmpeg/ffmpeg.exe" -version 2>/dev/null | head -1)"
[ -n "${FFMPEG:-}" ] || FFMPEG="$(ffmpeg -version 2>/dev/null | head -1)"
[ -n "${FFMPEG:-}" ] || FFMPEG="no-ffmpeg"

FINGERPRINT="$(
    {
        echo "$COMMIT"
        echo "$TREE"
        echo "$TRACKED"
        echo "$DIRTY_COUNT"
        echo "$DIRTY"
        echo "$LOCK"
        echo "$DEPS"
        echo "$MODELS"
        echo "$FFMPEG"
    } | sha256sum | cut -c1-16
)"

if [ "$SHORT" -eq 0 ]; then
    echo "repo      : $ROOT"
    echo "commit    : $COMMIT"
    echo "tree      : $TREE"
    echo "tracked   : $TRACKED"
    echo "dirty     : $DIRTY_COUNT file(s) modified, hash $DIRTY"
    echo "npm lock  : $LOCK"
    echo "python    : $PYVER / deps $DEPS"
    echo "models    : $MODELS"
    echo "ffmpeg    : $FFMPEG"
    echo
fi
echo "FINGERPRINT: $FINGERPRINT"

if [ "$SHORT" -eq 0 ]; then
    echo
    echo "Compare this line with the other machine. Same commit but a different"
    echo "fingerprint means the dependencies, models or ffmpeg differ; a different"
    echo "commit means 'git pull' is needed on one side."
fi
