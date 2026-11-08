# Local setup (Windows)

Everything below is already installed in this checkout. This file documents what
is where, and how to start the app.

## Start

PowerShell / Windows Terminal:

```powershell
.\run-backend.ps1      # http://localhost:8000
.\run-frontend.ps1     # http://localhost:5173   (second terminal)
```

MSYS2 / Git Bash (what this checkout is normally driven from):

```bash
./run-backend.sh       # same servers, same ports
./run-frontend.sh
./run-backend.sh --check    # resolve paths only, start nothing
```

Both launchers put `tools/ffmpeg` on `PATH` and set `HF_HOME` to `models/`. The
`.sh` versions also locate `node`/`npm` when the Windows PATH is not inherited,
which is the default in MSYS2.

### Use the official Node, not MSYS2's

MSYS2 ships a MinGW build of Node at `C:\msys64\mingw64\bin\node.exe` (v24.13),
and a plain MSYS2 shell puts it first in `PATH`. That build reports
`process.config.variables.shlib_suffix = "dll.a"`, which is exactly what rolldown
uses to decide which native binding to load: it then requires
`@rolldown/binding-win32-x64-gnu`, while `npm install` fetched the `-msvc`
binding that the official Node needs. Vite dies with:

```
Cannot find module '@rolldown/binding-win32-x64-gnu'
Cannot find native binding ...
```

`run-frontend.sh` now detects a MinGW node and switches to
`C:\Program Files\nodejs` before starting Vite. If you run `npm run dev` by hand,
make sure `node --version` resolves to `C:\Program Files\nodejs\node.exe`
(official, `shlib_suffix` = `so.137`), not the `mingw64` one.

The frontend talks to `http://localhost:8000` by default (`frontend/src/config.js`).
Point it elsewhere with `$env:VITE_API_URL = "http://..."` (PowerShell) or
`VITE_API_URL=... ./run-frontend.sh` (shell) before starting it.

### Line endings (important in MSYS2)

`core.autocrlf=true` is set in the **repository** config, not only in Git for
Windows' system config. Without it, MSYS2's own git (which has no system or user
config of its own) sees the CRLF working tree against the LF index and reports
every tracked file as modified, and a stray `git add -A` from that shell would
rewrite the whole repo with CRLF. Verified: `git status` from MSYS2 now shows only
real changes.


## API keys (the only thing not installed for you)

`backend/.env` exists and is configured: `DEEPSEEK_API_KEY` (answering) and
`GROQ_API_KEY` (Whisper transcription). Both were verified against the live APIs.
It is gitignored (`.gitignore` rule `**/.env`) and has never been committed.

| Key | Used for | Required? |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | answering questions (cheapest, OpenAI-compatible, also reads frames) | recommended |
| `OPENAI_API_KEY` | answering (fallback) + Whisper transcription | one LLM key + one ASR key |
| `GROQ_API_KEY` | Whisper transcription (fast, cheap) | recommended |
| `HF_TOKEN` | last-resort LLM (Llama-3.1-8B) and last-resort ASR | optional |

Providers are chosen at import time in `backend/llama.py` and `backend/whisper.py`.
Current setup resolves to **DeepSeek `deepseek-flash`** for answers and
**Groq `whisper-large-v3`** for transcription -- both confirmed by an end-to-end
run (upload a 10s clip -> transcript with word timings -> indexed in Qdrant ->
`/ask` answered with timestamps).

`backend/whisper.py` had two bugs that only surfaced with a Groq-only setup:
the startup line reported "HF Inference API" (it keyed the branch on
`OPENAI_API_KEY`), and `MAX_WORKERS` stayed at 4 instead of 16. Both fixed.

## What is installed

| Path | What | Size |
| --- | --- | --- |
| `venv\` | Python 3.12 virtualenv: FastAPI, uvicorn, torch 2.15 **CPU**, torchvision, transformers, sentence-transformers, qdrant-client, yt-dlp, openai, ffmpeg-python | ~1.0 GB |
| `models\` | Hugging Face cache (`HF_HOME`): `paraphrase-multilingual-MiniLM-L12-v2` (text embeddings) + `clip-vit-base-patch32` (frame embeddings) | ~1.6 GB |
| `tools\ffmpeg\` | static ffmpeg 9.0.2 + ffprobe (`run-backend.ps1` prepends it to `PATH`) | ~300 MB |
| `frontend\node_modules\` | Vite 8 + React 19 frontend deps | ~250 MB |
| `_setup\` | the install scripts and their logs (gitignored) | small |

`backend/requirements.txt` was missing two packages that the code imports
(`qdrant-client`, `requests`); both were added and installed.

Vector search runs in **embedded Qdrant** (`QdrantClient(path="./qdrant_data")`),
so no Qdrant server or Docker is needed. `main.py` creates `backend/qdrant_data`
on first run.

## Verify

```powershell
curl http://localhost:8000/debug/qdrant-counts   # {"text_points":0,"frame_points":0}
```

## Keeping keys out of git

`backend/.env` holds the real keys and is ignored by `.gitignore` rule `**/.env`;
`backend/.env.example` (tracked) lists the variables with empty values.

A local hook at `.git/hooks/pre-commit` blocks any commit that stages a `.env`
file or that has a key-shaped string in the index. It is local only -- nothing
about it is pushed -- and it can be re-tested at any time:

```bash
sh _setup/test_hook.sh     # 5 checks, all should PASS
```

Manual check before pushing:

```bash
git diff --cached --name-only | grep -E '(^|/)\.env$'   # empty = ok
git grep --cached -I -nE 'sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{30,}'
```

Note the option order: `--cached` must come **before** the pattern. The other
order is a fatal error (exit 128), which a hook would read as "no match".

## Notes

- Run the backend from `backend\` (what `run-backend.ps1` does): `qdrant_store.py`
  uses a relative `./qdrant_data` path.
- `video-analysis-pipeline` needs no extra install -- its four requirements
  (`yt-dlp`, `openai`, `python-dotenv`, `pydantic`) are already in the venv. Run it
  with `venv\Scripts\python.exe -m pipeline --help` from that folder, or use its
  Dockerfile.
- `WHISPER_LOCAL=1` in `.env` switches transcription to local faster-whisper; that
  package is **not** installed (`uv pip install faster-whisper`) because the API
  route is roughly 40x faster on CPU.
- Windows symlink warning from `huggingface_hub` is harmless (no Developer Mode);
  the cache just uses copies instead of links.
