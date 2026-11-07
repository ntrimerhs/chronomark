"""Per-segment analysis: frames -> batched vision calls -> one JSON result."""
import json
import logging
import re
import shutil
from pathlib import Path

from pipeline import frames as frames_mod
from pipeline import utils
from pipeline.config import Settings
from pipeline.llm import DeepSeekClient
from pipeline.segment import Segment

_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def load_prompt() -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / "segment_analysis.txt"
    return path.read_text(encoding="utf-8")


def _parse_json(raw: str) -> dict | None:
    cleaned = _FENCE.sub("", raw.strip()).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except ValueError:
        return None


def analyse_segment(
    segment: Segment,
    settings: Settings,
    client: DeepSeekClient,
    run_dir: Path,
) -> dict:
    """Analyse one segment. Returns the parsed result or an error record."""
    segment_id = segment.segment_id
    cache_file = run_dir / "analysis" / f"{segment_id}.json"

    cached = utils.read_json(cache_file)
    if cached:
        logging.info("%s: cached", segment_id)
        return cached

    frames_dir = run_dir / "frames" / segment_id
    try:
        extracted = frames_mod.extract_frames(
            segment.path,
            frames_dir,
            interval_sec=settings.frame_interval_sec,
            max_side=settings.image_max_side,
            quality=settings.jpeg_quality,
            max_frames=settings.max_frames_per_segment,
        )
    except Exception as exc:  # noqa: BLE001 - reported per segment
        logging.error("%s: frame extraction failed: %s", segment_id, exc)
        return {"segment_id": segment_id, "start_sec": segment.start_sec,
                "end_sec": segment.end_sec, "error": f"frames: {exc}"}

    template = load_prompt()
    prompt = (template
              .replace("{{segment_id}}", segment_id)
              .replace("{{start_hms}}", utils.hms(segment.start_sec))
              .replace("{{end_hms}}", utils.hms(segment.end_sec)))

    # chronological, labelled with absolute times
    timed = [(segment.start_sec + index * settings.frame_interval_sec, path)
             for index, path in enumerate(extracted)]
    batch_size = max(1, settings.max_frames_per_request)

    raw_chunks: list[str] = []
    observations: list[dict] = []
    summaries: list[str] = []
    uncertainties: list[str] = []
    language = ""

    for offset in range(0, len(timed), batch_size):
        batch = timed[offset:offset + batch_size]
        try:
            raw = client.analyse_frames(batch, prompt)
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: request failed: %s", segment_id, exc)
            uncertainties.append(f"request failed for batch at {utils.hms(batch[0][0])}: {exc}")
            continue

        raw_chunks.append(raw)
        parsed = _parse_json(raw)
        if parsed is None:
            logging.warning("%s: invalid JSON, retrying once", segment_id)
            try:
                raw = client.analyse_frames(batch, prompt + "\n\nReturn valid JSON only, matching the schema.")
                raw_chunks.append(raw)
                parsed = _parse_json(raw)
            except Exception as exc:  # noqa: BLE001
                logging.error("%s: retry failed: %s", segment_id, exc)
        if parsed is None:
            uncertainties.append(f"unparseable reply for batch at {utils.hms(batch[0][0])}")
            continue

        if not language and parsed.get("language"):
            language = str(parsed["language"])
        observations.extend(parsed.get("observations") or [])
        if parsed.get("segment_summary"):
            summaries.append(str(parsed["segment_summary"]))
        uncertainties.extend(str(item) for item in (parsed.get("uncertainties") or []))

    result = {
        "segment_id": segment_id,
        "language": language,
        "start_sec": segment.start_sec,
        "end_sec": segment.end_sec,
        "observations": sorted(observations, key=lambda o: str(o.get("timestamp", ""))),
        "segment_summary": " ".join(summaries).strip(),
        "uncertainties": uncertainties,
        "frame_count": len(extracted),
    }

    utils.write_json(cache_file, result)
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{segment_id}.txt").write_text("\n\n---\n\n".join(raw_chunks), encoding="utf-8")

    if not settings.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    return result