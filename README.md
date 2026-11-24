# ChronoMark

Upload a lecture recording or a study handout, then ask it questions. Every answer
comes back cited — `p. 12` for a document, `12:40` for a video — because every
line of the answer is grounded in a page or a moment that was actually read.

The interesting part of this project is what it refuses to do on its own machine:
the heavy lifting (OCR, transcription, embeddings, answers) is API-side, and the
box itself only orchestrates. The API answers an upload in **under a second**, a
fleet of workers does the indexing, and a long video can be transcribed without
ever being downloaded.

---

## Architecture

```
                    ┌──────────────┐
   browser ────────▶│  FastAPI API  │────  uploads/queue/<job>.json ────┐
      │             └──────────────┘                                    │
      │                    │  status: jobs/<job>.json                   ▼
      │                    │                                    ┌────────────────┐
      │                    ▼                                    │    workers     │
      │             ┌─────────────┐                             │ (N replicas)   │
      └────────────▶│     R2      │◀───── presigned URLs ──────▶│ claim by rename│
                    └─────────────┘                             └───────┬────────┘
                                                                        │
                        ┌───────────────┬───────────────┬───────────────┼──────────────┐
                        ▼               ▼               ▼               ▼              ▼
                 Google Document   Groq Whisper    OpenAI embed     DeepSeek      Cloudflare
                      AI              (ASR)        3-small (1536d)   (answers)      Stream
                        │               │               │               │              │
                        └───────────────┴───────▶ ┌─────▼─────┐ ◀───────┴──────────────┘
                                                  │  Qdrant   │
                                                  │  vectors  │
                                                  └───────────┘
```

### Document path

| Step | Where it runs |
|---|---|
| Upload (PDF/PPTX/DOCX, ≤ 40 MB) | API writes it to R2 and one job file, replies `200` |
| OCR + page structure | **Google Document AI**, 14-page pieces in parallel |
| Figure reading | Groq vision |
| Chunking + embeddings | **OpenAI `text-embedding-3-small`** (1536d) |
| Index | Qdrant (`video_text_segments_1536`) |
| Answers | **DeepSeek**, streamed to the browser over SSE |

### Video path — three routes, cheapest first

| Route | When | Local CPU |
|---|---|---|
| **Groq direct** | local file ≤ `GROQ_DIRECT_MAX_MB` (24) | none |
| **Cloudflare edge audio** | R2 object, `MEDIA_TRANSFORM_ENABLED=1`, source ≤ 10 min and ≤ 100 MB | none — the edge returns M4A slices, Groq fetches them |
| **Cloudflare Stream** | remote media, `STREAM_TRANSCODE=1`, token has `Stream: Edit` | none — Stream transcodes, Groq fetches the MP4 URL |
| **ffmpeg + chunking** | everything else (long videos without a Stream token) | audio extract + chunk split |

The edge route uses Media Transformations on the zone:

```
https://<zone>/cdn-cgi/media/mode=audio,time=<offset>s,duration=60s,format=m4a/https://<r2-public-domain>/<key>
```

One request yields at most 60 seconds, so a video becomes one slice per minute,
transcribed in parallel (`MEDIA_TRANSFORM_WORKERS`) and stitched back with their
time offsets. Measured: a 135-second clip → 3 slices → 21 segments in **5.6s**,
with the last segment correctly at 130.7s and no ffmpeg involved.

Frame extraction and CLIP embeddings are gated by `FRAME_EMBEDDINGS` (off by
default): the most expensive thing the box used to do, and the answers are
transcript-backed anyway.

---

## Stack and what it costs

| Service | Role | Price |
|---|---|---|
| Google Document AI | OCR, page and paragraph structure | $1.50 / 1,000 pages, first 1,000 free monthly |
| Groq `whisper-large-v3` | speech to text | $0.04–0.111 / hour of audio |
| OpenAI `text-embedding-3-small` | 1536d embeddings | $0.02 / 1M tokens |
| DeepSeek `deepseek-flash` | answers, quizzes, flashcards | per token |
| Qdrant Cloud | vector store | plan-dependent |
| Cloudflare R2 | video + document storage | storage + operations |
| Cloudflare Stream | optional transcoding | $5 / 1,000 min stored, $1 / 1,000 min delivered |

A 23-page handout costs roughly **$0.04** end to end (OCR dominates), and about
$0.0002 of that is embeddings.

---

## Quick start

```bash
git clone https://github.com/ntrimerhs/chronomark.git
cd chronomark
cp backend/.env.example backend/.env   # then fill it in (see below)
docker compose up -d --build
```

The frontend is served on `:8080`, the API on `:37712`. A Caddy instance in front
(`chronomark.0digital.xyz`) terminates TLS and proxies `/api/*` to the backend with
the prefix stripped.

### Environment (`backend/.env`)

**Required**

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | answers and study material |
| `GROQ_API_KEY` | speech to text, figure vision |
| `QDRANT_URL`, `QDRANT_API_KEY` | vector store |
| `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` | object storage |
| `EMBEDDING_API_KEY` | OpenAI key for embeddings (falls back to `OPENAI_API_KEY`) |

**Provider switches**

| Variable | Default | Meaning |
|---|---|---|
| `EMBEDDING_PROVIDER` | `auto` | `openai` / `local` (local MiniLM, 384d, free) |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `text-embedding-3-small`, `1536` | must match the collection name |
| `TEXT_COLLECTION` | `video_text_segments_<dim>` | which Qdrant collection is read |
| `FRAME_EMBEDDINGS` | `0` | `1` re-enables frame extraction + CLIP |
| `STREAM_TRANSCODE` | `0` | `1` enables the Cloudflare Stream route |

**Document AI (optional)** — without these, PDFs go through pypdf and scans are
missed:

| Variable | Purpose |
|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | path to the service-account JSON (mounted read-only from `backend/secrets/`) |
| `DOCUMENT_AI_PROJECT`, `DOCUMENT_AI_LOCATION`, `DOCUMENT_AI_PROCESSOR_ID` | processor coordinates |
| `DOCUMENT_AI_CONCURRENCY` | pieces in flight (default 3) |

**Cloudflare edge audio (optional)** — audio extraction at the edge needs an R2
public domain on the same zone (no API token at all):

| Variable | Purpose |
|---|---|
| `MEDIA_TRANSFORM_ENABLED` | `1` turns the route on |
| `MEDIA_TRANSFORM_ZONE` | zone with Transformations enabled, e.g. `0digital.xyz` |
| `MEDIA_PUBLIC_ORIGIN` | public R2 domain, e.g. `https://media.0digital.xyz` |
| `MEDIA_TRANSFORM_SLICE`, `_WORKERS`, `_MAX_SECONDS` | 60s / 4 / 600 defaults |

**Cloudflare Stream (optional)** — the whole-video route needs an API token with
*Stream: Edit*, not the R2 S3 keys:

| Variable | Purpose |
|---|---|
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Stream API access |
| `STREAM_CLIP_SECONDS`, `STREAM_CLIP_WORKERS` | long-video chunking (defaults 1200s / 4) |

**Tuning**

| Variable | Default | Meaning |
|---|---|---|
| `MAX_CONCURRENT_DOC_JOBS` / `MAX_CONCURRENT_VIDEO_JOBS` | `3` / `2` | in-process gates inside one worker |
| `WORKER_CONCURRENCY` | `2` in worker.py, `1` in compose | jobs per worker container |
| `GROQ_DIRECT_MAX_MB` | `24` | above this, video takes another route |
| `LLM_CONTINUE_ROUNDS` | `4` | how many times a truncated answer is continued |

---

## How the queue works

The API never runs a job. It writes `<job_id>.json` into `backend/queue/` and
replies. A worker claims a job by **renaming** it to `.processing` — an atomic
operation, so any number of workers can share the directory without ever taking
the same job twice. Progress is written to `backend/jobs/<job_id>.json`, which the
API serves from `/upload-status/{job_id}`.

```bash
docker compose up -d --scale worker=4 worker      # more workers, same queue
docker compose logs -f worker                     # watch claims and completions
```

Two replicas run by default, each doing one job at a time with a 900 MB cap.
Measured on a 2 vCPU / 3 GB box: ~300 MB per worker, ~1.5 GB free — so two is
comfortable, four is the practical ceiling, and the queue absorbs a burst of
twenty uploads by simply making them wait.

---

## Isolation that was measured, not assumed

| Change | Effect |
|---|---|
| Blocking work moved off the event loop (`run_in_threadpool`) | 5 concurrent questions: **23.4s → 5.9s**; a healthcheck during the burst **22.3s → 0.005s** |
| Separate document/video upload gates | a video decode no longer holds PDF uploads |
| Document AI pieces in parallel | 23-page handout **13.8s → 9.3s** |
| Answer streaming (SSE) | first token at **2.28s** instead of waiting ~5s for the whole answer |
| API + worker split | upload answered in **847 ms** (was the whole job) |

---

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/upload-document` | accept a PDF/PPTX/DOCX, enqueue indexing |
| `POST /uploadfile/` | accept a video (streamed to R2), enqueue analysis |
| `GET /upload-status/{job_id}` | progress, read from the shared job store |
| `POST /api/document/ask` | answer over a document |
| `POST /api/document/ask/stream` | the same answer as SSE, token by token |
| `POST /api/document/quiz`, `/flashcards`, `/notes` | study material |
| `POST /ask` | answer over a video, with second-level citations |
| `GET /api/documents`, `/api/document/{id}`, `/{id}/chats` | library and conversations |

---

## Repository layout

```
backend/            FastAPI app, workers and the pipelines
  main.py           endpoints, ingestion jobs, video pipeline
  worker.py         the process that claims and runs jobs
  jobs.py           file-based queue + status store
  documents.py      PDF/PPTX/DOCX extraction (Document AI with a pypdf fallback)
  bert.py           embeddings (OpenAI or local MiniLM)
  llama.py          prompts, streaming, answer continuation
  whisper.py        ASR via Groq (direct media or extracted audio)
  cloudflare_media.py  optional edge audio route (audio-only M4A slices)
  cloudflare_stream.py  optional transcode route (whole video, long inputs)
  qdrant_store.py   collections and search
frontend/           React 19 + Vite SPA (landing, video workspace, document workspace)
docker-compose.yml  api, worker (x2), frontend, WARP egress
```

---

## Known limitations

- **`.pptx` and `.docx` are parsed locally** — Document AI covers PDFs and images.
- **Long videos still need ffmpeg** unless the Stream route is enabled: the edge
  audio route is capped at 10 minutes / 100 MB by Cloudflare, and the Stream route
  needs a token with `Stream: Edit` plus downloads enabled on the account.
- **Video answers are not streamed yet** — only the document chat is (SSE).
- **Document AI** costs real money past the free 1,000 pages/month, and the online
  endpoint takes at most 15 pages per request (hence the 14-page split).
- **Frame/visual search is off by default**; turn on `FRAME_EMBEDDINGS=1` and the
  box pays for CLIP again.
- The queue is filesystem-based on purpose: it survives restarts and needs no
  extra service, but it is single-host. Multi-host would want Redis behind the
  same interface.


---

## Current state (measured on the live box)

| Area | Result |
|---|---|
| Upload acknowledgement | **847 ms** — the API queues a job file and replies; workers do the reading |
| Document job (23 pages, 11 figures) | **24s** total, figures read in parallel (**8.0s** for 11) |
| Five concurrent questions | **5.9s** wall (was 23.4s serialised); healthcheck during the burst 0.005s |
| Answer streaming | first token at **2.28s**, ~2,600 delta frames for a long answer |
| Truncated answers | continued automatically; a stream that ends without a `finish_reason` is treated as cut |
| Edge audio (≤10 min) | 391s video → 7 slices → 113 segments in ~25s, no ffmpeg, no download |
| Stream route (>10 min) | 12-min clip → transcode ready 29.5s → 2.3 MB MP4 → Groq 6.7s, 59 segments |

Both workspaces now read the same: full-bleed panels, no marketing header, no chat
panel head, answers as plain text with pink `#` headings. The video player keeps its
own aspect ratio — letterboxed, with space above and below — rather than being
stretched.

### Known open items

- A video job can currently run twice for the same upload: the edge route
  transcribes, a later step raises, and the fallback re-runs the whole pipeline on
  a local copy. Costs a duplicate Groq call; needs one owner for the status and no
  silent fallback (see *Roadmap*).
- `.pptx` / `.docx` are still parsed locally (Document AI covers PDFs and images).
- Video answers are not streamed yet — only the document chat is.

### Roadmap

1. `pipelines/` package with a single `select_route()` that encodes each route's
   preconditions, so the four video routes stop being a chain of `except`
   fallbacks.
2. The worker imports `pipelines`, never `main`.
3. One writer for job status (monotonic progress), plus `route_used` and
   per-stage timings in the job record.
4. Tests for route selection and transcript merging; `make verify` runs them in
   seconds.
