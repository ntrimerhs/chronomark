import base64
import os
import re
import sys
import time
import wave
import requests as _requests
from dotenv import load_dotenv
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import random
from openai import OpenAI as _OpenAI

load_dotenv()

# Increase recursion limit for deep segment estimation in large videos
sys.setrecursionlimit(5000)

whisper_token = os.getenv("HF_TOKEN")
_openai_api_key = os.getenv("OPENAI_API_KEY")

MAX_SEGMENT_SECONDS = 30.0

_ASR_MODEL = "openai/whisper-large-v3-turbo"
_HF_ASR_FALLBACK_URL = f"https://router.huggingface.co/hf-inference/models/{_ASR_MODEL}"
_OPENAI_TRANSCRIPTION_MODEL = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")

# Groq serves Whisper through an OpenAI-compatible endpoint at roughly a third
# of OpenAI's price and much higher speed. Preferred whenever its key exists;
# the OpenAI path stays as the fallback.
_GROQ_API_KEY = os.getenv("GROQ_API_KEY")
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_GROQ_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")

# OpenAI Whisper API — fastest option (truly parallel, ~2s/chunk)
_openai_client = _OpenAI(api_key=_openai_api_key) if _openai_api_key else None
_groq_client = (
    _OpenAI(api_key=_GROQ_API_KEY, base_url=_GROQ_BASE_URL) if _GROQ_API_KEY else None
)

# Use dedicated Inference Endpoint when configured (always warm, no rate limits)
_endpoint_url = os.getenv("HF_WHISPER_ENDPOINT_URL")
_endpoint_token = os.getenv("HF_WHISPER_ENDPOINT_TOKEN")

# Groq is checked first because transcribe_audio prefers it whenever its key
# exists; keying this branch on _openai_client alone reported "HF Inference API"
# for a Groq-only setup, i.e. the log named a provider that was never used.
if _groq_client:
    print(f"[Whisper] Using Groq {_GROQ_MODEL}")
elif _openai_client:
    print("[Whisper] Using OpenAI Whisper API")
elif _endpoint_url and _endpoint_token:
    _asr_url = _endpoint_url
    _asr_token = _endpoint_token
    print("[Whisper] Using dedicated Inference Endpoint")
else:
    _asr_url = _HF_ASR_FALLBACK_URL
    _asr_token = whisper_token
    print("[Whisper] Using HF Inference API (direct HTTP)")

# Five minutes per chunk. The API transcribes long audio happily, and a longer
# chunk gives the model far more context than 30 seconds did -- a 13-minute
# lecture becomes 3 parallel calls instead of 26, with better accuracy per call.
CHUNK_SECONDS = 300

# The shared HF "hf-inference" endpoint is serverless infra: on a cold start
# (or under load) it can take longer to spin up whisper-large-v3 than the
# router's own gateway timeout allows, which surfaces as a 504 to us even
# though the request itself was fine. A dedicated Inference Endpoint skips
# this entirely and has no rate limits. Retrying with backoff smooths over
# any transient failures on either endpoint.
ASR_MAX_RETRIES = 3
ASR_RETRY_BACKOFF_SECONDS = 2  # dedicated endpoint: no cold starts
_RETRYABLE_MARKERS = ("504", "502", "503", "429", "gateway", "timeout", "timed out", "rate limit")


def _is_retryable_asr_error(exc):
    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_MARKERS)


# --- Language handling ------------------------------------------------------
#
# Whisper auto-detects the language of every request independently. Because we
# transcribe 60s chunks in parallel, one video can come back with some chunks
# read as Greek and others as Bulgarian/Russian/Turkish, which surfaces as
# transliterated or invented text partway through the transcript. So we detect
# the language ONCE from chunks sampled across the audio and pin it for every
# chunk, instead of hardcoding a language and breaking the other one.

SUPPORTED_LANGUAGES = ("el", "en")
LANGUAGE_PROBE_COUNT = 3

_GREEK_RANGES = (("Ͱ", "Ͽ"), ("ἀ", "῿"))

_LANGUAGE_ALIASES = {
    "el": "el", "ell": "el", "gre": "el", "greek": "el", "ελληνικά": "el",
    "en": "en", "eng": "en", "english": "en",
}

# No prompt by default, deliberately. A prompt looks like a free accuracy win,
# but Whisper conditions on it as if it were preceding transcript text: on a
# quiet or low-content chunk it echoes the prompt back verbatim as the
# "transcription". A domain-neutral instruction ("transcribe with correct
# accents") got emitted as a real segment when tested on a 6-minute Greek
# lesson, so the language pin carries the fix on its own.
#
# WHISPER_PROMPT_EL / WHISPER_PROMPT_EN opt into a prompt anyway — worth it for
# a corpus with fixed jargon or proper nouns. Use a bare comma-separated term
# list rather than a sentence, and note that echoed output is filtered by
# _looks_like_prompt_echo below but can only be suppressed heuristically.
def _prompt_for_language(language):
    if not language:
        return None
    return os.getenv(f"WHISPER_PROMPT_{language.upper()}") or None


def _normalize_for_echo_match(text):
    return re.sub(r"\W+", " ", (text or "").lower(), flags=re.UNICODE).strip()


def _looks_like_prompt_echo(text, prompt):
    """True when a segment is the prompt read back instead of the actual audio."""
    if not prompt or not text:
        return False

    normalized_prompt = _normalize_for_echo_match(prompt)
    normalized_text = _normalize_for_echo_match(text)
    if not normalized_prompt or not normalized_text:
        return False

    # Substring both ways: a partial echo lands inside the prompt, while a
    # repeated echo ("<prompt>. <prompt>. ...") contains it.
    return normalized_text in normalized_prompt or normalized_prompt in normalized_text


def _drop_prompt_echoes(segments, prompt, audio_path):
    if not prompt:
        return segments

    kept = [s for s in segments if not _looks_like_prompt_echo(s.get("text"), prompt)]
    dropped = len(segments) - len(kept)
    if dropped:
        print(f"transcribe_audio: dropped {dropped} prompt-echo segment(s) from {audio_path}")
    return kept


def _normalize_language_code(value):
    """Map a Whisper language label ('greek', 'el', ...) to 'el'/'en', else None."""
    if not value:
        return None
    return _LANGUAGE_ALIASES.get(str(value).strip().lower())


def _script_vote(text):
    """Guess the language from the alphabet used, or None if there's too little signal."""
    greek = latin = 0
    for char in text or "":
        if any(low <= char <= high for low, high in _GREEK_RANGES):
            greek += 1
        elif "a" <= char.lower() <= "z":
            latin += 1

    if greek + latin < 8:
        return None
    if greek >= latin:
        return "el"
    # Latin-dominant output doesn't prove English on its own (Spanish, Italian
    # and a transliterated Greek reading all look the same here), so let the
    # caller weigh Whisper's own label first.
    return "en"


def _language_from_probe(data):
    """Infer 'el'/'en' from one unpinned transcription, or None to abstain."""
    voted = _script_vote(data.get("text"))
    # Greek letters can only come from a Greek reading, and mislabelled Greek
    # audio is exactly the failure we're guarding against — so script wins here.
    if voted == "el":
        return "el"

    reported = _normalize_language_code(data.get("language"))
    if reported:
        return reported

    if not data.get("language"):
        # No label at all (the HF route doesn't return one) — script is all we have.
        return voted

    # A label we don't support (e.g. Greek misread as Bulgarian) and no Greek
    # script: abstain rather than guess, so this chunk doesn't skew the vote.
    return None


def _probe_language(audio_path):
    """Transcribe one chunk with auto-detect on and report what language it looks like."""
    # language=None on purpose: the whole point of the probe is to let Whisper
    # auto-detect. It used to read an undefined `language` name here and raise
    # NameError, which the caller logged as "language probe failed" and then fell
    # back to per-chunk auto-detect -- i.e. the probe never ran.
    if _groq_client:
        data = _transcribe_via_groq(audio_path, None)
    elif _openai_client:
        data = _transcribe_via_openai(audio_path, None)
    else:
        data = _transcribe_via_http(audio_path, None)
    return _language_from_probe(data)


def _sample_for_probing(chunks, probe_count):
    """Pick up to probe_count non-silent chunks spread evenly across the audio."""
    candidates = [chunk for chunk in chunks if not _is_silent_wav(str(chunk))]
    if not candidates or probe_count < 1:
        return []
    if len(candidates) <= probe_count:
        return candidates
    if probe_count == 1:
        return [candidates[0]]

    step = (len(candidates) - 1) / (probe_count - 1)
    return [candidates[round(index * step)] for index in range(probe_count)]


def detect_language(chunks, probe_count=LANGUAGE_PROBE_COUNT):
    """Detect the audio's language from sampled chunks.

    Returns 'el', 'en', or None when the probes disagree or fail — None leaves
    Whisper on per-chunk auto-detect, i.e. the previous behaviour.
    """
    override = _normalize_language_code(os.getenv("WHISPER_LANGUAGE"))
    if override:
        print(f"[Whisper] language pinned to '{override}' via WHISPER_LANGUAGE")
        return override

    probes = _sample_for_probing(chunks, probe_count)
    if not probes:
        return None

    votes = []
    with ThreadPoolExecutor(max_workers=len(probes)) as executor:
        futures = [executor.submit(_probe_language, str(chunk)) for chunk in probes]
        for future in as_completed(futures):
            try:
                vote = future.result()
            except Exception as e:
                print(f"[Whisper] language probe failed: {type(e).__name__}: {e}")
                continue
            if vote in SUPPORTED_LANGUAGES:
                votes.append(vote)

    if not votes:
        print("[Whisper] language detection inconclusive; leaving auto-detect on")
        return None

    winner = max(SUPPORTED_LANGUAGES, key=votes.count)
    print(f"[Whisper] detected language '{winner}' from {len(probes)} probes (votes: {votes})")
    return winner


def _is_silent_wav(audio_path: str, silence_threshold: float = 0.001) -> bool:
    """Return True if the WAV file is empty or near-silent (RMS < 0.1% of full scale)."""
    import struct
    try:
        with wave.open(audio_path, "rb") as wav_file:
            raw = wav_file.readframes(wav_file.getnframes())
        if not raw or len(raw) < 2:
            return True
        sample_count = len(raw) // 2
        samples = struct.unpack(f"<{sample_count}h", raw[:sample_count * 2])
        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
        return (rms / 32768.0) < silence_threshold
    except Exception:
        return False


def split_audio(audio_path, output_dir, chunk_seconds=CHUNK_SECONDS):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chunk_paths = []

    with wave.open(str(audio_path), "rb") as wav:
        params = wav.getparams()

        sample_rate = wav.getframerate()
        frames_per_chunk = sample_rate * chunk_seconds

        total_frames = wav.getnframes()
        total_chunks = math.ceil(total_frames / frames_per_chunk)

        for i in range(total_chunks):
            frames = wav.readframes(frames_per_chunk)

            chunk_path = output_dir / f"chunk_{i:04d}.wav"

            with wave.open(str(chunk_path), "wb") as out:
                out.setparams(params)
                out.writeframes(frames)

            chunk_paths.append(chunk_path)

    return chunk_paths


def _coerce_to_dict(output):
    if isinstance(output, dict):
        return output
    if hasattr(output, "model_dump"):
        return output.model_dump()
    if hasattr(output, "dict"):
        return output.dict()
    if hasattr(output, "__dict__"):
        return vars(output)
    return {"text": str(output)}


def _normalize_words(raw_words):
    """Flatten Whisper's word timings into {"w", "start", "end"} dicts."""
    words = []
    for item in raw_words or []:
        if isinstance(item, dict):
            word = item
        elif hasattr(item, "model_dump"):
            word = item.model_dump()
        elif hasattr(item, "dict"):
            word = item.dict()
        elif hasattr(item, "__dict__"):
            word = vars(item)
        else:
            continue

        text = (word.get("word") or word.get("text") or "").strip()
        start = word.get("start")
        end = word.get("end")
        if not text or not isinstance(start, (int, float)):
            continue
        words.append(
            {
                "w": text,
                "start": float(start),
                "end": float(end) if isinstance(end, (int, float)) else float(start),
            }
        )
    return words


def _normalize_segments(data):
    raw_chunks = data.get("chunks") or data.get("segments") or []
    segments = []

    for item in raw_chunks:
        if isinstance(item, dict):
            chunk = item
        elif hasattr(item, "model_dump"):
            chunk = item.model_dump()
        elif hasattr(item, "dict"):
            chunk = item.dict()
        elif hasattr(item, "__dict__"):
            chunk = vars(item)
        else:
            continue

        timestamp = chunk.get("timestamp")
        start = chunk.get("start")
        end = chunk.get("end")

        if isinstance(timestamp, (list, tuple)) and len(timestamp) == 2:
            if start is None:
                start = timestamp[0]
            if end is None:
                end = timestamp[1]

        segments.append(
            {
                "start": start,
                "end": end,
                "text": (chunk.get("text") or "").strip(),
            }
        )

    return segments


def _wav_duration_seconds(audio_path):
    try:
        with wave.open(audio_path, "rb") as wav_file:
            frame_count = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            if sample_rate <= 0:
                return None
            return frame_count / float(sample_rate)
    except Exception:
        return None


def _split_text_units(text):
    units = [part.strip() for part in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if part.strip()]
    if units:
        return units
    fallback = (text or "").strip().split()
    if not fallback:
        return []
    group_size = 12
    return [" ".join(fallback[index:index + group_size]) for index in range(0, len(fallback), group_size)]


def _estimate_segments_from_text(text, start, end, max_segment_seconds=MAX_SEGMENT_SECONDS):
    clean_text = (text or "").strip()
    if not clean_text:
        return []

    if start is None:
        start = 0.0
    if end is None or end <= start:
        end = start + max_segment_seconds

    total_duration = max(float(end) - float(start), 0.0)
    units = _split_text_units(clean_text)
    if not units:
        return []

    total_chars = sum(max(len(unit), 1) for unit in units)
    cursor = float(start)
    estimated = []

    for index, unit in enumerate(units):
        proportional_duration = total_duration * (max(len(unit), 1) / total_chars) if total_chars else 0.0
        chunk_end = float(end) if index == len(units) - 1 else cursor + proportional_duration
        estimated.append(
            {
                "start": round(cursor, 3),
                "end": round(chunk_end, 3),
                "text": unit,
            }
        )
        cursor = chunk_end

    if total_duration > max_segment_seconds:
        refined = []
        for item in estimated:
            duration = (item["end"] or 0.0) - (item["start"] or 0.0)
            if duration <= max_segment_seconds:
                refined.append(item)
                continue
            refined.extend(
                _estimate_segments_from_text(
                    item.get("text", ""),
                    item.get("start"),
                    item.get("end"),
                    max_segment_seconds=max_segment_seconds,
                )
            )
        return refined

    return estimated


def _refine_segments(segments, audio_path, fallback_text, max_segment_seconds=MAX_SEGMENT_SECONDS):
    """
    Only estimate segments as a fallback if we have no segments or they're invalid.
    Trust Whisper's timestamps—don't try to recursively subdivide them (causes deep recursion).
    """
    if not segments:
        # No segments: estimate from full text
        duration = _wav_duration_seconds(audio_path)
        return _estimate_segments_from_text(fallback_text, 0.0, duration, max_segment_seconds=max_segment_seconds)

    # Filter segments: only keep those with valid text and timestamps
    valid_segments = []
    for item in segments:
        start = item.get("start")
        end = item.get("end")
        text = (item.get("text") or "").strip()

        if text and isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            valid_segments.append({
                "start": round(float(start), 3),
                "end": round(float(end), 3),
                "text": text,
            })

    # If we got valid segments from Whisper, return them as-is
    # (don't try to recursively subdivide—that causes recursion depth errors)
    if valid_segments:
        return valid_segments

    # Fallback: estimate from full text if no valid segments
    duration = _wav_duration_seconds(audio_path)
    return _estimate_segments_from_text(fallback_text, 0.0, duration, max_segment_seconds=max_segment_seconds)


def _transcribe_via_openai(audio_path: str, language: str | None = None) -> dict:
    """Transcribe via the configured OpenAI speech-to-text model.

    Passing language=None leaves auto-detect on, which is what the language
    probes need; every real chunk should pass the detected language.
    """
    options = {}
    if language:
        options["language"] = language
        prompt = _prompt_for_language(language)
        if prompt:
            options["prompt"] = prompt

    with open(audio_path, "rb") as f:
        request = {
            "model": _OPENAI_TRANSCRIPTION_MODEL,
            "file": f,
            "timeout": 60,  # fail fast instead of hanging on a stalled connection
            **options,
        }
        if _OPENAI_TRANSCRIPTION_MODEL == "whisper-1":
            request["response_format"] = "verbose_json"
            # Word timings are the accuracy floor for every citation
            # downstream: a phrase can only be placed as precisely as the
            # timings we keep. Segment boundaries here average 7.2s and reach
            # 30s, so anything snapped to a segment start is seconds off by
            # construction.
            request["timestamp_granularities"] = ["word", "segment"]
        response = _openai_client.audio.transcriptions.create(**request)
    return response.model_dump()


def _transcribe_via_groq(audio_path: str, language: str | None = None) -> dict:
    """Transcribe through Groq's Whisper endpoint."""
    options = {}
    if language:
        options["language"] = language

    def request(granularities):
        with open(audio_path, "rb") as handle:
            return _groq_client.audio.transcriptions.create(
                file=(Path(audio_path).name, handle.read()),
                model=_GROQ_MODEL,
                response_format="verbose_json",
                timestamp_granularities=granularities,
                **options,
            )

    try:
        response = request(["word", "segment"])
    except Exception as exc:
        # the endpoint may reject word granularity; segments alone are enough
        print(f"[Whisper] Groq rejected word timestamps ({exc}); retrying with segments")
        response = request(["segment"])
    return response.model_dump()


def _transcribe_via_http(audio_path: str, language: str | None = None) -> dict:
    """POST audio directly to the configured ASR endpoint; no InferenceClient routing."""
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    headers = {
        "Authorization": f"Bearer {_asr_token}",
        "x-wait-for-model": "true",  # hold connection until model is warm instead of 503
    }

    # HF's ASR route only accepts generation options in the JSON body form, so
    # pinning a language means sending base64 instead of raw bytes. This route
    # is the fallback (OpenAI wins whenever OPENAI_API_KEY is set) and is not
    # exercised here, so fall back to the raw-bytes form if it's rejected
    # rather than failing the chunk over a language hint.
    if language:
        try:
            resp = _requests.post(
                _asr_url,
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "inputs": base64.b64encode(audio_bytes).decode("ascii"),
                    "parameters": {
                        "generate_kwargs": {"language": language, "task": "transcribe"}
                    },
                },
                timeout=300,
            )
            if resp.ok:
                return resp.json()
            print(
                f"[ASR] language-pinned request rejected ({resp.status_code}); "
                "retrying with auto-detect"
            )
        except Exception as e:
            print(
                f"[ASR] language-pinned request failed ({type(e).__name__}: {e}); "
                "retrying with auto-detect"
            )

    resp = _requests.post(
        _asr_url,
        headers={**headers, "Content-Type": "audio/wav"},
        data=audio_bytes,
        timeout=300,
    )
    if not resp.ok:
        print(f"[ASR] {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    return resp.json()


def transcribe_audio(audio_path: str, language: str | None = None):
    if _is_silent_wav(audio_path):
        print(f"transcribe_audio: skipping silent chunk {audio_path}")
        return {"text": "", "segments": [], "timestamps": []}

    data = None
    last_exc = None

    for attempt in range(1, ASR_MAX_RETRIES + 1):
        try:
            data = (
                _transcribe_via_groq(audio_path, language=language)
                if _groq_client
                else _transcribe_via_openai(audio_path, language=language)
                if _openai_client
                else _transcribe_via_http(audio_path, language=language)
            )
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            if attempt == ASR_MAX_RETRIES:
                raise
            wait_seconds = ASR_RETRY_BACKOFF_SECONDS * attempt + random.uniform(0, 2)
            print(
                f"transcribe_audio: attempt {attempt}/{ASR_MAX_RETRIES} failed "
                f"for {audio_path} ({type(e).__name__}: {e}); retrying in {wait_seconds:.1f}s..."
            )
            time.sleep(wait_seconds)

    if data is None:
        raise last_exc

    try:
        segments = _normalize_segments(data)
        refined = _refine_segments(segments, audio_path, data.get("text") or "")
    except Exception as e:
        print(f"ERROR processing audio {audio_path}: {e}")
        import traceback
        traceback.print_exc()
        raise

    prompt = _prompt_for_language(language)
    kept = _drop_prompt_echoes(refined, prompt, audio_path)

    # Rebuild the flat text from the surviving segments when anything was
    # dropped, so the echo can't leak back in through data["text"].
    text = (
        " ".join(s["text"] for s in kept if s.get("text")).strip()
        if len(kept) != len(refined)
        else (data.get("text") or "").strip()
    )

    return {
        "text": text,
        "segments": kept,
        "timestamps": kept,
        "words": _normalize_words(data.get("words")),
    }

def _merge_chunk_segments(chunks, results):
    """Offset, clamp, and remove duplicate segments produced at chunk edges."""
    merged = []

    for index in sorted(results):
        result = results[index]
        offset = index * CHUNK_SECONDS
        chunk_duration = _wav_duration_seconds(str(chunks[index])) or CHUNK_SECONDS
        chunk_end = offset + chunk_duration

        for segment in result.get("segments", []):
            start = segment.get("start")
            end = segment.get("end")
            text = (segment.get("text") or "").strip()
            if not text or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                continue

            start = max(0.0, min(float(start), chunk_duration)) + offset
            end = max(start - offset, min(float(end), chunk_duration)) + offset
            if end <= start:
                continue

            current = {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
            }

            if merged:
                previous = merged[-1]
                previous_text = " ".join(previous["text"].casefold().split())
                current_text = " ".join(text.casefold().split())
                overlaps = current["start"] <= previous["end"] + 0.5
                duplicate = current_text == previous_text or current_text in previous_text or previous_text in current_text
                if overlaps and duplicate:
                    if len(current_text) > len(previous_text):
                        previous["text"] = text
                    previous["start"] = min(previous["start"], current["start"])
                    previous["end"] = max(previous["end"], current["end"])
                    continue

            merged.append(current)

    return merged


# The shared/serverless HF route needs a low cap to avoid getting throttled,
# but OpenAI's transcription API has much higher per-account concurrency
# limits and each request is truly independent, so it's safe to fan out far
# more chunks at once there -- this is what actually lets a 6-minute video
# (~12 chunks) transcribe in a handful of seconds instead of several rounds.
# Groq counts here too: same OpenAI-compatible API, same high concurrency.
MAX_WORKERS = 16 if (_openai_client or _groq_client) else 4


_LOCAL_MODEL = None
_LOCAL_MODEL_NAME = os.getenv("WHISPER_LOCAL_MODEL", "small")
# Off by default. Local faster-whisper on CPU measured 0.73x realtime -- 18
# minutes for a 13-minute lecture, against ~20 seconds for the API. Enable it
# with WHISPER_LOCAL=1 only on a machine with a GPU, where it becomes faster
# and free.
_LOCAL_ENABLED = os.getenv("WHISPER_LOCAL", "0").strip().lower() in ("1", "true", "yes")


def _get_local_model():
    """Load faster-whisper once and keep it warm for the process."""
    global _LOCAL_MODEL
    if _LOCAL_MODEL is None:
        from faster_whisper import WhisperModel

        print(f"[Whisper] loading local model '{_LOCAL_MODEL_NAME}' (cpu, int8)")
        _LOCAL_MODEL = WhisperModel(
            _LOCAL_MODEL_NAME, device="cpu", compute_type="int8"
        )
    return _LOCAL_MODEL


def _transcribe_via_local(audio_path: str, language: str | None = None) -> dict:
    """Transcribe on this machine with faster-whisper.

    Removes the per-minute API cost entirely. Word timings come for free, which
    the API path has to request separately, and nothing leaves the machine.
    """
    import time

    model = _get_local_model()
    started = time.perf_counter()
    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )

    segments, words = [], []
    for segment in segments_iter:
        segments.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": (segment.text or "").strip(),
        })
        for word in getattr(segment, "words", None) or []:
            words.append({
                "w": (word.word or "").strip(),
                "start": float(word.start),
                "end": float(word.end),
            })

    elapsed = time.perf_counter() - started
    print(
        f"[Whisper] local '{_LOCAL_MODEL_NAME}': {len(segments)} segments, "
        f"{len(words)} words in {elapsed:.1f}s (lang={getattr(info, 'language', '?')})"
    )
    return {
        "text": " ".join(s["text"] for s in segments).strip(),
        "segments": segments,
        "timestamps": segments,
        "words": words,
        "language": getattr(info, "language", language),
    }


def transcribe_audio_chunks(audio_path, language=None, on_progress=None):
    """Transcribe a WAV in parallel chunks.

    language: 'el', 'en', or None to detect it from the audio. Whatever is used
    is pinned across every chunk so the language can't drift mid-transcript.
    on_progress: optional callback(completed_count, total_chunks), invoked
    after every chunk finishes (success or failure) so callers can surface
    granular progress instead of only finding out once everything is done.
    """
    audio_path = Path(audio_path)

    # Local transcription first when enabled: no per-minute cost, word timings
    # included, and it runs the whole file in one pass instead of chunking for
    # parallel API calls.
    if _LOCAL_ENABLED:
        try:
            result = _transcribe_via_local(str(audio_path), language)
            if on_progress:
                try:
                    on_progress(1, 1)
                except Exception:
                    pass
            return result
        except Exception as exc:
            print(f"[Whisper] local transcription failed ({exc}); falling back to the API")

    # Give each video its own chunk subfolder (named after the audio file's
    # stem) instead of a single shared "temp_chunks" folder. With one shared
    # folder, leftover chunks from a crashed/previous run, or a second
    # upload processed while this one is still running, could collide with
    # or get mixed into this video's chunk_0000.wav-style filenames.
    chunk_dir = Path("temp_chunks") / audio_path.stem
    chunks = split_audio(audio_path, chunk_dir)

    print(f"Created {len(chunks)} chunks")

    language = _normalize_language_code(language) or detect_language(chunks)

    all_segments = []

    max_workers = min(MAX_WORKERS, len(chunks)) or 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        futures = {}

        for index, chunk in enumerate(chunks):
            futures[
                executor.submit(transcribe_audio, str(chunk), language)
            ] = index

        results = {}

        for future in as_completed(futures):

            index = futures[future]

            try:
                result = future.result()

                print(f"\nChunk {index}")
                print("Text:", result["text"][:80] if result["text"] else "[EMPTY]")
                print("Segments:", len(result["segments"]))

                results[index] = result
            except Exception as e:
                print(f"Chunk {index} failed: {type(e).__name__}: {e}")

            if on_progress:
                try:
                    on_progress(len(results), len(chunks))
                except Exception as e:
                    print(f"[Whisper] on_progress callback failed: {e}")

    # --- retry any chunks that failed on the first pass ---
    failed_indices = [i for i in range(len(chunks)) if i not in results]
    if failed_indices:
        print(f"Retrying {len(failed_indices)} failed chunks...")
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(failed_indices))) as executor:
            retry_futures = {
                executor.submit(transcribe_audio, str(chunks[i]), language): i
                for i in failed_indices
            }
            for future in as_completed(retry_futures):
                index = retry_futures[future]
                try:
                    results[index] = future.result()
                    print(f"Chunk {index} succeeded on retry")
                except Exception as e:
                    print(f"Chunk {index} failed again: {e}")

                if on_progress:
                    try:
                        on_progress(len(results), len(chunks))
                    except Exception as e:
                        print(f"[Whisper] on_progress callback failed: {e}")


    all_segments = _merge_chunk_segments(chunks, results)

    # Word timings need the same chunk offset applied as segments, or a citation
    # resolved against them lands at the wrong point in a long video.
    all_words = []
    for index in sorted(results):
        offset = index * CHUNK_SECONDS
        for word in (results[index] or {}).get("words") or []:
            start = word.get("start")
            end = word.get("end")
            if not isinstance(start, (int, float)):
                continue
            all_words.append({
                "w": word.get("w"),
                "start": float(start) + offset,
                "end": (float(end) if isinstance(end, (int, float)) else float(start)) + offset,
            })
    all_words.sort(key=lambda word: word["start"])

    print("Successful chunks:", len(results))
    print("Failed chunks:", len(chunks) - len(results))

    # Add placeholder segments for permanently failed chunks
    failed_indices = [i for i in range(len(chunks)) if i not in results]
    if failed_indices:
        for index in sorted(failed_indices):
            offset = index * CHUNK_SECONDS
            all_segments.append({
                "start": round(offset, 3),
                "end": round(offset + CHUNK_SECONDS, 3),
                "text": "[TRANSCRIPTION FAILED - AUDIO UNAVAILABLE]"
            })
        print(f"Added {len(failed_indices)} placeholder segments for failed chunks")

    # Sort all segments by start time
    all_segments.sort(key=lambda s: s.get("start", 0))
    full_text = " ".join(segment["text"] for segment in all_segments)

    # Delete temporary chunks AFTER transcription is complete
    for chunk in chunks:
        chunk.unlink(missing_ok=True)
    try:
        chunk_dir.rmdir()
    except OSError:
        pass  # not empty (unexpected leftover file) or already removed

    print("Merged text length:", len(full_text))
    print("Merged segments:", len(all_segments))

    return {
        "text": full_text.strip(),
        "segments": all_segments,
        "timestamps": all_segments,
        "words": all_words,
        "language": language,
    }