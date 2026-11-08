#!/usr/bin/env bash
# MSYS2 / Git Bash launcher for the frontend dev server.
#
#   ./run-frontend.sh            start Vite on http://localhost:5173
#   ./run-frontend.sh --check    print what it would use, start nothing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FE="$ROOT/frontend"

# A node built with MinGW (MSYS2 ships one at /mingw64/bin/node) reports
# process.config.variables.shlib_suffix = "dll.a", and rolldown keys its native
# binding choice on exactly that: it then requires
# @rolldown/binding-win32-x64-gnu, while npm installed the -msvc binding that the
# official Windows node needs. The result is
#   Cannot find module '@rolldown/binding-win32-x64-gnu'
# followed by "Cannot find native binding", i.e. vite never starts.
node_is_mingw() {
    [ "$(node -p 'process.config.variables.shlib_suffix' 2>/dev/null)" = "dll.a" ]
}

# Prefer the official Windows Node when the shell offers no node at all, or only
# a MinGW one. Stop at the first hit: %APPDATA%\npm holds only shims whose bash
# wrappers resolve Windows paths wrongly under MSYS2.
if ! command -v node >/dev/null 2>&1 || node_is_mingw; then
    for d in "/c/Program Files/nodejs" "/c/Program Files (x86)/nodejs" \
             "${LOCALAPPDATA:-$HOME/AppData/Local}/Programs/nodejs"; do
        if [ -x "$d/node.exe" ]; then
            export PATH="$d:$PATH"
            break
        fi
    done
fi

[ -d "$FE/node_modules" ] || { echo "missing $FE/node_modules -- run 'npm install' there first" >&2; exit 1; }

if node_is_mingw; then
    echo "run-frontend.sh: still using a MinGW node ($(node --version) at $(command -v node))." >&2
    echo "Install the official Windows Node.js, or run: npm install @rolldown/binding-win32-x64-gnu" >&2
    exit 1
fi

if [ "${1:-}" = "--check" ]; then
    echo "ROOT    : $ROOT"
    echo "node    : $(node --version 2>&1)  ($(command -v node))"
    echo "npm     : $(npm --version 2>&1)"
    echo "deps    : $(ls "$FE/node_modules" | wc -l) packages"
    echo "API base: ${VITE_API_URL:-http://localhost:8000 (default)}"
    exit 0
fi

cd "$FE"
echo "Starting frontend on http://localhost:5173 (Ctrl+C to stop)"
exec npm run dev
