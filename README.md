# ChronoMark

Turn a lecture recording or a handout into something you can ask questions about.
ChronoMark transcribes the video, reads the slides and figures, indexes every
passage, and answers in plain language with a citation that jumps to the exact
moment (`12:40`) or page (`p. 12`) the answer came from.

Two pipelines, one index:

```
video    ──ffmpeg──► audio ──Whisper──► transcript ─┐
                    └► frames ──vision OCR──► text ──┤
                                                      ├──► embeddings ──► Qdrant ──► chat
document ──pypdf / python-pptx / python-docx──► pages ┤
                    └► figures ──vision──► descriptions ─┘
```

Everything heavy (transcription, vision, chat, vectors, file storage) runs on
hosted APIs, so the server itself only does ffmpeg, page parsing and a small CPU
embedding model.

## What it does

**Video**

- Upload a file from disk, or paste a YouTube link. The video goes straight to
  Cloudflare R2; the server only keeps the derived WAV and frames.
- Whisper (Groq `whisper-large-v3` by default) transcribes it in 5-minute chunks
  in parallel, with the language detected once and pinned across the file.
- Coverage frames every 30 seconds are read by a vision model, so an answer can
  reproduce code or a slide that was never spoken aloud.
- Answers cite `mm:ss`; clicking a citation seeks the player.

**Documents (PDF / PowerPoint / Word)**

- Every page is extracted and chunked with its heading, so a chunk always knows
  which section it belongs to.
- Scanned pages fall back to OCR; PowerPoint speaker notes are indexed too.
- Figures are read once at ingest and stored as `[figure p.N]` descriptions with
  a plain-text diagram, so a question about "the tree in Figure 14" can be
  answered and the tree can be drawn in the answer.
- Answers cite `p. N`; clicking one opens the PDF at that page.
- Study tools read the same index: multiple-choice quiz (with LaTeX), flashcards
  and a full-document study guide.

**Answer style**

Answers are grounded in the material, but written to teach rather than to quote:
every formula gets a plain-language gloss, every symbol is defined the first time
it appears, dense notation is broken into parts, and a concrete example from the
material comes before the general rule. Mathematics is written in LaTeX and
rendered with KaTeX. Long answers continue in a new message instead of being cut
off, and a Greek document is always answered in Greek.

## Stack

| Layer | Choice |
| --- | --- |
| Frontend | React 19, Vite 8, react-router, video.js, KaTeX (remark-math / rehype-katex) |
| Backend | FastAPI + uvicorn, ffmpeg, pypdf / python-pptx / python-docx |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` (384 dims, CPU) |
| Vectors | Qdrant (server / Cloud; embedded local store also supported) |
| Speech | Groq Whisper `whisper-large-v3` (OpenAI and HF also supported) |
| LLM + vision | DeepSeek (OpenAI-compatible), with OpenAI and HF fallbacks |
| Files | Cloudflare R2 via presigned URLs |
| Serving | nginx for the SPA, Caddy in front on the VPS |

## Repository layout

```
backend/
  main.py                FastAPI app: upload endpoints, jobs, /ask, document API
  whisper.py             chunked transcription, language detection, retries
  video_processing.py    ffmpeg: audio extraction, frame extraction, normalising
  documents.py           page extraction (PDF/PPTX/DOCX), figures, chunking
  bert.py                embeddings, idle unload, thread and batch limits
  qdrant_store.py        collections, upsert, search, per-video filtering
  llama.py               prompts, answering, quiz/flashcards/notes, figure reader
  services/r2_service.py presigned URLs, multipart upload, retention helpers
  scripts/set_r2_cors.py applies the bucket CORS policy (optional)
frontend/
  src/components/        hero, upload page, documents page, chat, palette
  src/styles/            the whole visual system (scoped skins)
  nginx.conf             SPA fallback, cache headers, gzip
docker-compose.yml       backend + frontend (+ warp container for yt-dlp egress)
```

## Quick start with Docker

```bash
cp backend/.env.example backend/.env   # fill in the keys you have
docker compose up -d --build
```

- Frontend: <http://localhost:8080>
- API: the port mapped in `docker-compose.yml` (`ports:`) to container `8000`

At minimum the stack wants `DEEPSEEK_API_KEY` (or `OPENAI_API_KEY`) and
`GROQ_API_KEY`, a vector store (`QDRANT_URL`, or empty for the embedded store)
and the four `R2_*` variables for file storage.

## Local development

```bash
# backend
cd backend
python -m venv ../.venv
../.venv/Scripts/pip install -r requirements.txt        # Windows
../.venv/bin/pip install -r requirements.txt            # macOS / Linux
../.venv/Scripts/python -m uvicorn main:app --reload --port 8000

# frontend (second terminal)
cd frontend
npm install
npm run dev      # http://localhost:5173
```

`run-backend.ps1` / `run-frontend.ps1` (and the `.sh` equivalents) wrap exactly
these two commands.

The embedded Qdrant store (`./qdrant_data`) can only be opened by one process at
a time: point `QDRANT_URL` at a Qdrant server to run a local backend and a Docker
backend side by side. `migrate_qdrant_to_server.py` copies an existing embedded
index into a server.

## API

Video

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/uploadfile/` | Upload a video; streams it to R2, starts analysis |
| GET | `/api/get-upload-url` | Presigned PUT so the browser uploads straight to R2 |
| POST | `/api/process-video` | Analyse a video that is already in R2 |
| POST | `/download-youtube/` | Download via yt-dlp, push to R2, analyse |
| GET | `/upload-status/{job_id}` | Job stage, progress, result |
| GET | `/api/video-stream/{file_key}` | 302 to a fresh presigned playback URL |
| GET | `/api/video-presence/{file_key}` | Heartbeat that keeps the R2 copy alive |

Documents

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/upload-document` | Upload PDF/PPTX/DOCX (max 40 MB) and index it |
| GET | `/api/documents` | Indexed documents, newest first |
| GET | `/api/document/{doc_id}` | Pages, language, and where to fetch the file |
| GET | `/api/document-file/{doc_id}` | Same-origin relay of the original file |
| GET | `/api/document-stream/{file_key}` | 302 to R2 (used when bucket CORS allows) |
| DELETE | `/api/document/{doc_id}` | Remove points, R2 object and metadata |
| POST | `/api/document/ask` | Ask a question; answers cite `p. N` |
| POST | `/api/document/quiz` | Multiple-choice questions plus the figures they use |
| POST | `/api/document/flashcards` | Term/definition cards |
| POST | `/api/document/notes` | Full study guide with citations |

Diagnostics: `/debug/qdrant-counts`, `/debug/segments`, `/metrics`.

## Configuration

Everything lives in `backend/.env` (see `backend/.env.example` for the full,
commented list). The ones worth knowing:

| Variable | Default | What it does |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | – | Answering and vision |
| `GROQ_API_KEY` | – | Whisper transcription |
| `QDRANT_URL` / `QDRANT_API_KEY` | empty = embedded | Vector store |
| `R2_*` | – | File storage |
| `WHISPER_LANGUAGE` | auto | Pin the transcript language (`el`, `en`, …) |
| `VIDEO_RETENTION_MINUTES` | `60` | Delete the R2 copy when nobody is watching |
| `ARTIFACT_RETENTION_DAYS` | `7` | Age out local WAVs and frame folders |
| `MAX_CONCURRENT_JOBS` | `2` | Heavy jobs allowed at once (the rest queue) |
| `COVERAGE_INTERVAL_SEC` | `30` | Frame sampling for OCR |
| `FRAME_MAX_WIDTH` | `960` | Frame width handed to the vision model |
| `OCR_MAX_FRAMES` | `24` | Vision calls per video, evenly spaced |
| `WHISPER_MAX_WORKERS` | `6` | Parallel transcription chunks per job |
| `EMBEDDING_THREADS` | `1` | Torch threads (leave a core for ffmpeg) |
| `EMBEDDING_BATCH` | `32` | Peak memory during embedding |
| `EMBEDDING_IDLE_UNLOAD_SEC` | `900` | Drop the model after this idle time |
| `PUBLIC_SITE_ORIGIN` | `https://chronomark.0digital.xyz` | Origin the CORS check looks for |
| `YT_DLP_PROXY` | – | Optional SOCKS proxy for YouTube downloads |

## Capacity

Measured on a 2 vCPU / 3.8 GB machine with the hosted APIs doing the heavy work:

| | |
| --- | --- |
| 3 parallel short video uploads | 15–23 s each, ~945 MB peak |
| 4 parallel questions | all served, 5–17 s (LLM-bound) |
| 3 parallel PDF uploads | ~5 s each |
| Comfortable | 2 concurrent analyses, ~10 active readers |
| Upgrade trigger | swap in use, backend RSS > 1.5 GB, load average > 2 |

`MAX_CONCURRENT_JOBS` is what stops a burst from pushing the box into swap: a
third upload waits its turn instead of taking the server down with it. Nothing
else needs new hardware — the knobs above trade detail for cost.

## Notes and limitations

- Job state lives in memory. A restart loses the progress of uploads in flight
  (indexed results survive; job status does not).
- One uvicorn worker by design: more workers would each load the embedding model
  and would split the in-memory job table.
- Documents are relayed through the API unless the R2 bucket has a CORS policy
  for this origin. `scripts/set_r2_cors.py` applies one, and the app switches to
  direct R2 reads automatically once it exists.
- Older exploration files (`inspect_*.py`, `_type_para1.py`, `CONTEXT.md`,
  `SETUP.md`, `deploy/`) are kept for reference.
