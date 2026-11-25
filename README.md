# ChronoMark

Upload a lecture recording or a study handout, then ask it questions. Every answer
comes back cited — `p. 12` for a document, `12:40` for a video — because every
line of the answer is grounded in a page or a moment that was actually read.

The interesting part of this project is what it refuses to do on its own machine:
the heavy lifting (OCR, transcription, embeddings, answers) is API-side, and the
box itself only orchestrates. The API answers an upload in **under a second**, a
fleet of workers does the indexing, and a long video can be transcribed without
ever being downloaded.

Accounts are the front door: both workspaces and every endpoint that costs money
sit behind a signed-in user, and registration works without a mail server — either
through Google/GitHub, or through an endpoint that creates the account already
confirmed.

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

### YouTube — imported without touching the disk

`/download-youtube/` no longer downloads to `/tmp` and then uploads. `yt-dlp`
writes to **stdout** (`-o -`) and that pipe goes straight into
`r2_service.upload_stream()`, so a recording becomes an R2 object without ever
existing as a file. For adaptive streams the video-only and audio-only tracks are
streamed to R2 separately and muxed there (`ffmpeg -c copy`, presigned inputs),
which keeps every byte off the container's disk.

The picker prefers a muxed MP4 when one is at least `YT_DLP_MIN_MUXED_HEIGHT`
(720p), otherwise the best adaptive pair under `YT_DLP_MAX_HEIGHT` (1080p). HLS
variants are ranked last on purpose: through a pipe, `ffmpeg` on an m3u8 fails
(exit 8), so a format that only works when written to disk is not a format this
route can use.

Measured: a muxed 360p clip, 27.2 MB in **21s**; an adaptive 1080p pair,
245.7 + 29.3 MB → 275.4 MB muxed in **94s**, with `/tmp` empty afterwards.

---

## Accounts, and the wall around the workspaces

Authentication is Supabase; the database is where the rule actually lives. The
publishable key is in the browser by design, so **row level security**, not the
key, is what protects a row.

### Database (`backend/sql/001_users.sql`)

| Table | Holds |
|---|---|
| `profiles` | one row per account (`display_name`, `avatar_url`, `plan`) |
| `workspaces` | one row per document or recording (`file_key`, `source_url`, `status`, `page_count`, `duration_sec`, `meta`) |
| `messages` | chat turns, with `citations` as JSON |
| `usage_events` | what was spent, per account and per action |
| `schema_migrations` | what has been applied |

A `security definer` trigger on `auth.users` creates the profile on signup
(`full_name` → `name` → the email local part), and five RLS policies make every
row readable and writable only by the `auth.uid()` that owns it. The script is
idempotent, so it can be run twice.

### Four ways in

| Flow | How |
|---|---|
| **Sign in** | `supabase.auth.signInWithPassword` from the browser |
| **Email sign up** | `POST /auth/signup` — creates the account already confirmed through the admin API, because this project has no SMTP and the default flow would end in an inbox nobody reads |
| **Google / GitHub** | `signInWithOAuth` → provider → `/auth/callback`, where the session is already in `localStorage` and the page forwards to `?next` |
| **Reset** | `/reset-password`, the link returns there |

A bare word is a username: `admin` signs in as `admin@chronomark.app`
(`USERNAME_DOMAIN` in `lib/supabaseClient.js`).

### The gate is on the server, not only in the router

`frontend/src/components/RequireAuth.jsx` sends a signed-out visitor from
`/upload` or `/documents` to `/register?next=…`, and shows a quiet placeholder
while the session is read so the workspace never flashes first. A redirect is a
courtesy though, not a wall — anyone can POST to the API directly. So
`backend/auth_guard.py` verifies the Supabase access token against the project's
JWKS (ES256/RS256; `cryptography` is already in the image, no PyJWT) and answers
`401` on the endpoints that cost money — and on the whole `/document…` prefix,
not a list of routes, so a route added next month is not born unprotected.

| Protected | Open — a `<video>` or an `<iframe>` cannot send a header |
|---|---|
| `/uploadfile`, `/download-youtube`, `/ask` | `/api/video-stream/*`, `/api/document-stream/*` |
| `/api/upload-document`, `/api/process-video`, `/api/get-upload-url` | `/video-frames/*`, `/uploads`, `/audio`, `/frames`, `/health` |
| `/api/documents` and every `/api/document/*` route | |
| `/api/document-file/*` — by header, or by the signature in its `file_url` | |

Every browser call carries the token because `src/lib/authFetch.js` wraps `fetch`
and `src/lib/authAxios.js` wraps axios, each once, adding `Authorization: Bearer …`
for our own API only — so a call written next month is authenticated too. Both are
needed: axios talks XHR and never touches `window.fetch`, which is exactly how a
signed-in visitor used to get "please sign in" from the upload page.

### One directory per account

The bucket is not shared any more. Every object an account uploads lands under
`documents/<dir>/…` or `videos/<dir>/…`, where `<dir>` is an HMAC of the user id
keyed by `R2_SCOPE_SECRET` (`backend/services/user_scope.py`):

```
documents/776dcd4730995730467f89d1/9af3f568…-01_graphsintro.pdf   ← admin
documents/876eb8f91f87dc6be8a78834/bd9368bd…-theme-showcase.pdf   ← xrysa
```

The directory is a hash, not the id. A UUID in a key would tell anyone who sees a
URL exactly who owns the file, and the id is the one value an attacker already
holds — it is in their own token — so it must not be the thing that protects the
folder. Twenty-four hex characters, stable per account, impossible to enumerate.

The wall itself is `owner_id`: written on the document record by the worker that
indexed it (the API passes it through the job file), checked on every read.
Someone else's document answers `404`, exactly like one that does not exist — a
`403` would confirm the id is real, which is the one bit an enumerating client is
after. `_owned_document()` is the only function that decides, and the video side
refuses a `file_key` outside the caller's directory on `/api/process-video`.

Objects uploaded before scoping are moved into their owner's directory by
`backend/scripts/migrate_scopes.py`: copy, `HEAD` the copy to confirm the size,
then delete the old key — so an interrupted run leaves a duplicate, never a hole.

```bash
docker compose exec -T backend python scripts/migrate_scopes.py --owner <user-id> --dry-run
```

An `<iframe>` cannot send a header, so the document `file_url` is not a bare
route: the authenticated request that returns it mints an expiring signature
(`?expires=…&sig=…`, six hours) and `/api/document-file` accepts either that
signature or a header. A tampered or expired one is a `401`.


### The frontend

React 19 + Vite SPA with five surfaces:

```
/              landing
/register      create an account   (/login signs in, /auth/callback is the OAuth return)
/workspaces    dashboard, document list, history, settings
/documents     document analysis   (viewer + chat)
/upload        video analysis      (player + chat)
```

`/workspaces`, `/documents` and `/upload` are behind `RequireAuth`. All three use
the same sidebar — `components/common/AppSidebar.jsx` — whose shape is the
document workspace's: wordmark (the way home), one primary action, search, the
list grouped by day, and one pinned card at the bottom. The workspace page's four
views sit in a strip beside the top-bar breadcrumb, because the sidebar is the
list of what you have, not a second navigation.

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
| Supabase | accounts, Postgres, row level security | the free tier is enough here |

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

The frontend needs its Supabase values at **build** time — Vite bakes them in — so
`docker-compose.yml` passes them as build args:

```yaml
frontend:
  build:
    args:
      VITE_SUPABASE_URL: ${SUPABASE_URL}
      VITE_SUPABASE_PUBLISHABLE_KEY: ${SUPABASE_PUBLISHABLE_KEY}
```

Then apply the schema once, from a machine that can reach the database:

```bash
psql "$DATABASE_URL" -f backend/sql/001_users.sql
```

### Environment (`backend/.env`)

**Required**

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | answers and study material |
| `GROQ_API_KEY` | speech to text, figure vision |
| `QDRANT_URL`, `QDRANT_API_KEY` | vector store |
| `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` | object storage |
| `R2_SCOPE_SECRET` | any long random string; turns a user id into that account's bucket directory and signs the document `file_url`s. **Rotating it orphans every object uploaded before the rotation** |
| `EMBEDDING_API_KEY` | OpenAI key for embeddings (falls back to `OPENAI_API_KEY`) |

**Accounts**

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | project URL |
| `SUPABASE_PUBLISHABLE_KEY` | browser-side key; also a build arg for the frontend |
| `SUPABASE_SECRET_KEY` | server only — `POST /auth/signup` uses it to create confirmed users |
| `SUPABASE_JWKS_URL` | `…/auth/v1/.well-known/jwks.json`; what `auth_guard.py` verifies against |
| `SUPABASE_JWT_SECRET` | optional, only for an HS256 project |
| `SUPABASE_JWT_AUDIENCE` | optional, default `authenticated` |

**YouTube ingest**

| Variable | Default | Meaning |
|---|---|---|
| `YT_DLP_MODE` | `auto` | `auto` prefers a muxed file, `dash` forces the split pair |
| `YT_DLP_MAX_HEIGHT` | `1080` | ceiling for adaptive video |
| `YT_DLP_MIN_MUXED_HEIGHT` | `720` | below this, split instead of taking the muxed file |
| `YT_DLP_DISK_FLOOR_MB` | `2500` | refuse a job that would eat the disk (only muxing uses it) |
| `YT_DLP_TIMEOUT` | `3600` | seconds before a download is killed |
| `YT_DLP_PROXY` | — | egress, e.g. `socks5://warp:1080`; YouTube refuses most datacentre IPs |

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

`Auth` means the request must carry `Authorization: Bearer <supabase access token>`.

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /auth/signup` | — | create an account, already confirmed |
| `POST /api/upload-document` | yes | accept a PDF/PPTX/DOCX, enqueue indexing |
| `POST /uploadfile/` | yes | accept a video (streamed to R2), enqueue analysis |
| `POST /download-youtube/` | yes | import a URL straight into R2, then analyse |
| `GET /upload-status/{job_id}` | — | progress, read from the shared job store |
| `POST /api/document/ask` | yes | answer over a document |
| `POST /api/document/ask/stream` | yes | the same answer as SSE, token by token |
| `POST /api/document/quiz`, `/flashcards`, `/notes` | yes | study material |
| `POST /ask` | yes | answer over a video, with second-level citations |
| `GET /api/documents`, `/api/document/{id}`, `/{id}/chats` | — | library and conversations |
| `GET /health` | — | liveness |

A `401` from one of the guarded endpoints means the token was missing, expired, or
signed by another project — the body says which.

---

## Repository layout

```
backend/            FastAPI app, workers and the pipelines
  main.py           endpoints, ingestion jobs, video pipeline
  auth_guard.py     Supabase JWT verification + the middleware that enforces it
  worker.py         the process that claims and runs jobs
  jobs.py           file-based queue + status store
  documents.py      PDF/PPTX/DOCX extraction (Document AI with a pypdf fallback)
  youtube_ingest.py diskless YouTube → R2 (stdout pipe, or a split pair muxed in R2)
  bert.py           embeddings (OpenAI or local MiniLM)
  llama.py          prompts, streaming, answer continuation
  whisper.py        ASR via Groq (direct media or extracted audio)
  cloudflare_media.py  optional edge audio route (audio-only M4A slices)
  cloudflare_stream.py  optional transcode route (whole video, long inputs)
  qdrant_store.py   collections and search
  services/user_scope.py  user id → that account's R2 directory (HMAC)
  scripts/migrate_scopes.py  move pre-scoping objects into their owner's directory
  sql/001_users.sql schema, trigger and RLS policies
frontend/           React 19 + Vite SPA
  src/components/common/AppSidebar.jsx     the one sidebar
  src/components/RequireAuth.jsx           the redirect
  src/lib/authFetch.js                     the bearer token, added once for fetch
  src/lib/authAxios.js                     ... and once for axios
  src/lib/supabaseClient.js                the client and the username mapping
  src/components/workspace/Workspaces.jsx  dashboard, list, history, settings
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
- **The library is per account, but it is still the file store, not Postgres** —
  `owner_id` and the per-account bucket directory isolate every document and video,
  while the `workspaces`/`messages` tables (with their RLS policies) remain unused.
  Moving the records into them is the next step, and the ownership model is already
  the shape those tables expect.
- **Video playback is protected by an unguessable key, not a signature** — a
  `<video src>` cannot send a header, so `/api/video-stream/<key>` stays open, and
  the key carries the owner's directory hash. Documents get a signed `file_url`
  instead; videos would get the same treatment if they were worth the round trip.
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
| YouTube → R2, muxed 360p | 27.2 MB in **21s**, `/tmp` untouched |
| YouTube → R2, adaptive 1080p | 245.7 + 29.3 MB → 275.4 MB muxed in **94s**, `/tmp` empty after |
| Auth gate | the costly endpoints answer `401` without a token, `422`/`200` with one |
| Per-account isolation | admin sees 1 document, xrysa 1 — each list empty of the other's; the other's `doc_id` answers `404` on read, chats, quiz, ask and delete; an upload lands in `documents/<hash-of-the-uploader>/` |
| Signed media URL | owner's `file_url` → `200`, no header and no signature → `401`, tampered signature → `401`, another account's document → `401` |
| Video scoping | a 29 KB 2-second clip went to `videos/<xrysa-hash>/…`; admin's `/api/process-video` on that key → `403` |
| Sign-up without a mailer | account created already confirmed; the profile row is made by the trigger |
| Sidebar | one component in all three workspaces; no second implementation left to drift |

Both workspaces read the same: full-bleed panels, no marketing header, no chat
panel head, answers as plain text with pink `#` headings. The video player keeps
its own aspect ratio — letterboxed, with space above and below — rather than being
stretched.

### Where this is going

1. **Move the records into Postgres**: `workspaces`/`messages` rows per account,
   with `owner_id` and the bucket directory already the shape they expect — the
   file store is what runs today.
2. `pipelines/` package with a single `select_route()` that encodes each route's
   preconditions, so the four video routes stop being a chain of `except`
   fallbacks, and the worker imports `pipelines` instead of `main`.
3. One writer for job status (monotonic progress), plus `route_used` and per-stage
   timings in the job record.
4. Signed URLs for video playback too, not only for documents.
5. Tests for route selection and transcript merging; `make verify` runs them in
   seconds.

---

## License

ChronoMark is source-available under the
[Functional Source License, Version 1.1, ALv2 Future License](LICENSE)
(FSL-1.1-ALv2).

- You may run it yourself, locally or on your own servers, with your own API keys,
  and you may read, modify and redistribute the code for any purpose other than a
  competing commercial product or service.
- You may not offer ChronoMark, or a substantially similar product built from it,
  as a hosted or commercial service that competes with ours.
- Two years after each version is released, that version becomes available under
  the Apache License, Version 2.0.

A managed, hosted version with no setup is available at
[chronomark.0digital.xyz](https://chronomark.0digital.xyz).
