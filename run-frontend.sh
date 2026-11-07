#!/usr/bin/env bash
# MSYS2 / Git Bash launcher for the frontend dev server.
#
#   ./run-frontend.sh            start Vite on http://localhost:5173
#   ./run-frontend.sh --check    print what it would use, start nothing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FE="$ROOT/frontend"

# MSYS2/MINGW shells do not always inherit the Windows PATH, so node/npm can be
# "command not found" even though they are installed. Take the first directory
# that actually contains node.exe -- and stop there, because %APPDATA%\npm holds
# only shims whose bash wrappers resolve Windows paths wrongly under MSYS2.
if ! command -v node >/dev/null 2>&1; then
    for d in "/c/Program Files/nodejs" "/c/Program Files (x86)/nodejs" \
             "${LOCALAPPDATA:-$HOME/AppData/Local}/Programs/nodejs"; do
        if [ -x "$d/node.exe" ]; then
            export PATH="$d:$PATH"
            break
        fi
    done
fi

[ -d "$FE/node_modules" ] || { echo "missing $FE/node_modules -- run 'npm install' there first" >&2; exit 1; }

if [ "${1:-}" = "--check" ]; then
    echo "ROOT    : $ROOT"
    echo "node    : $(node --version 2>&1)"
    echo "npm     : $(npm --version 2>&1)"
    echo "deps    : $(ls "$FE/node_modules" | wc -l) packages"
    echo "API base: ${VITE_API_URL:-http://localhost:8000 (default)}"
    exit 0
fi

cd "$FE"
echo "Starting frontend on http://localhost:5173 (Ctrl+C to stop)"
exec npm run dev
