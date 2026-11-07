# Ctrl + Vid — context for a new session

Everything below is the state of the project after the migration to
`ntrimerhs/chronomark`. Read this first; it saves re-deriving decisions that
took a long time to reach.

---

## 1. What the project is

A video analysis app. You upload a file or import from YouTube, it transcribes,
indexes, and answers questions about the video with clickable timestamps.

- **Backend** — FastAPI + uvicorn, Qdrant in local file mode, ffmpeg
- **Frontend** — React 19, Vite, video.js, `react-markdown`
- **Working directory** — `C:\Users\xrisa\Desktop\ai-video-tool`
- **Repos** — `fork` = `ntrimerhs/chronomark` (active), `upstream` =
  `ChristinaBezante/ai-video-tool` (frozen, to be archived — never push to it)

---

## 2. Provider stack

Nothing depends on OpenAI any more. OpenAI and HF remain only as fallbacks.

| Job | Provider | Model | Notes |
|---|---|---|---|
| Transcription | **Groq** | `whisper-large-v3` | free tier, 25MB per request |
| Answers | **DeepSeek** | `deepseek-flash` | thinking disabled |
| Citations / mappings | **DeepSeek** | `deepseek-flash` | JSON mode |
| Frame OCR | **DeepSeek** | `deepseek-flash` | vision, `detail` = original |
| Embeddings | **local** | `paraphrase-multilingual-MiniLM-L12-v2` | ~28s to load, once |

Keys live in `backend/.env` as `DEEPSEEK_API_KEY`, `GROQ_API_KEY`.
**They were rotated-out of a chat transcript once — rotate again if they leak.**

### Provider gotchas that cost real time

1. **DeepSeek thinking is ON by default.** It bills as output and can consume
   the entire `max_tokens` before any text is produced, which looks like an
   empty answer. Every call must pass:
   ```python
   extra_body={"thinking": {"type": "disabled"}}
   ```
2. **Groq caps uploads at 25MB.** The 5-minute chunking keeps chunks near
   9.6MB, so this is safe — do not remove the chunking.
3. **`yt-dlp` `best` is a single combined stream** and YouTube caps those at
   360p. 1080p only exists as separate video + audio streams:
   ```
   bestvideo[height<=1080]+bestaudio/best[height<=1080]/best
   ```
4. **DeepSeek `detail: "low"` downsizes to 512×512.** `high`/`original` keeps
   the source. Tokens are capped at 1024 per image either way, so `original`
   costs almost nothing extra.
5. **httpx keep-alive pools go stale.** A dead connection makes every retry
   fail identically. The fix, already in the pipeline, is to rebuild the client
   on transport errors, not just sleep and retry.

---

## 3. Cost

Per 13-minute lecture: **~$0.03**. Broken down: transcription ~$0.025,
answers ~$0.001, frame OCR ~$0.005. The earlier OpenAI stack was ~$0.10.

---

## 4. The timestamp system (the hard part)

Goal: when the answer mentions a worked example, cite the moment the lecturer
**explains** it, not the moment its slide first appeared.

### How it works now

```
[on screen] chunks   → say WHICH examples exist (no timestamp, by design)
[speech] chunks      → say WHEN each one is explained ([mm:ss-mm:ss])
```

1. `_cached_examples()` — one DeepSeek call per video, cached in
   `frames/<video_id>/examples.json`. Asks the model what the screen shows.
2. `extract_examples()` — in `llama.py`. Language-agnostic, file-type-agnostic,
   works for inline code with no files.
3. `map_examples_to_excerpts()` — maps each example to the speech excerpt that
   discusses it. **Must be given the full timeline**, not the retrieved window:
   the explaining segment is usually minutes away from the slide.
4. `_excerpt_time()` — resolves a label to a real moment. **Must search all
   points**, not the retrieved subset.
5. `_dedupe_timestamps()` — drops pills pointing at the same moment.

### Non-obvious rules that make it work

- **On-screen excerpts carry no timestamp.** When they did, the model cited
  the slide time (e.g. `0:20`) for every example on that slide.
- **Never fall back to `_ocr_example_timestamps`.** It returns the slide's own
  time, which is identical for all examples and looks authoritative while being
  wrong. No pills is better than four identical wrong pills.
- **The regex path is only a fast guess.** It looks for headings and file
  names; when it finds fewer than two, the model path takes over.

---

## 5. Answer style

Tuned in `llama.py`. The rules that matter:

- **Never use em dashes (—) or en dashes (–).** This is the single loudest
  machine-writing signal. Use a comma, a full stop, or «και».
- No emoji, no decorative symbols, no bullet lists unless asked.
- Banned openers: «Αξίζει να σημειωθεί», «Συνοψίζοντας», «Σε αυτό το πλαίσιο»,
  «Ωστόσο», «Επιπλέον» and their English equivalents.
- **Each example is followed by its own explanation.** Never collect all
  examples first and explain them afterwards.

---

## 6. Frame pipeline (separate, standalone)

`video-analysis-pipeline/` — an independent tool, not wired into the app.

```
YouTube → yt-dlp → 5-minute segments → frames → DeepSeek vision per segment
        → merge into final.md + final.json + run_manifest.json
```

- Detects the video's language from the frames and writes the report in it
  (majority vote across segments, because one segment may be an English IDE).
- Deterministic Markdown fallback if the model merge returns nothing.
- Last measured run: 13-minute Greek lecture, 12 requests, 32k tokens, ~4 min.
- **Not yet built as a Docker image.**

---

## 7. Known limitations (honest)

**OCR accuracy is capped by the source resolution.** A 640×360 capture gives a
code line about 12px tall, which puts a `+` at ~2px. `x = 3+5` reads as
`x = 345` and no upscaling fixes it. Frames are no longer downscaled and
downloads now request 1080p, so new uploads are fine; old ones are not.

**The lecturer must name what is on screen.** If they scroll silently through
code, examples are found but cannot be mapped to a moment. The pipeline
degrades gracefully: no example timestamps, normal retrieval instead.

**`_asks_for_examples` understands Greek and English only.**

**Two corrupted-Greek bugs have appeared before.** Editing with PowerShell
`Get-Content`/`Set-Content` without `-Encoding utf8` silently re-encoded Greek,
producing valid-looking strings that matched nothing, and at one point an
undefined variable. **Use Python for edits that touch Greek text.**

---

## 8. Pending work

1. Rotate the DeepSeek and Groq keys (exposed in a chat transcript).
2. `docker build` the frame pipeline — the only untested piece.
3. Possible: reranker to cut context tokens, answer caching, Batch API for
   non-interactive runs.
4. `handoff/` folder (patch + bundle) is no longer needed, safe to delete.

---

## 9. Running it

```powershell
# backend (needs its own terminal; model warmup takes ~28s at boot)
cd backend
uvicorn main:app

# frontend
cd frontend
npm run dev
```

The backend does **not** pick up `.env` or code changes without a restart.
Uploading needs no Docker; `ffmpeg` and `yt-dlp` are already installed.

### Useful endpoints

```
GET /debug/qdrant-counts      # text_points should exceed the transcript alone
GET /debug/segments           # what is indexed, with timestamps
GET /upload-status/{job_id}
```

### Log lines worth watching

```
[Whisper] Using Groq whisper-large-v3
[LLM] Using DeepSeek deepseek-flash
[OCR] N on-screen texts indexed        ← must not be 0
[Cite] N example timestamps from mapping
[Cite] example mapping skipped         ← tells you which exception
```

---

## 10. Verification discipline

This project has burned time on confident-but-wrong claims. What actually works:

- Measure before asserting. Numbers in the log beat reasoning about the code.
- A clean `py_compile` says nothing about runtime. The `NameError` that broke
  example mapping passed compilation.
- Check for mojibake explicitly: search for `\ufffd`, and separately confirm
  that Greek regexes contain codepoints in `\u0370–\u03ff`.
- Delete probe scripts and temp folders when done.
