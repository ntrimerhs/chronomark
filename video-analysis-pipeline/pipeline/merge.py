"""Merge per-segment analyses into a final report.

The LLM merge is best-effort: with a large input the model can return an empty
reply, and an empty final.md is worse than a plain one. So a deterministic
Markdown rendering is always available as the floor.
"""
import json
import logging
from pathlib import Path

from pipeline import utils
from pipeline.config import Settings
from pipeline.llm import DeepSeekClient

MAX_OBSERVATIONS_FOR_MERGE = 25


def load_prompt() -> str:
    path = Path(__file__).resolve().parent.parent / "prompts" / "final_merge.txt"
    return path.read_text(encoding="utf-8")


def _compact(segments: list[dict]) -> str:
    """Trim the payload: summaries always, observations capped per segment."""
    trimmed = []
    for segment in segments:
        trimmed.append({
            "segment_id": segment.get("segment_id"),
            "start_sec": segment.get("start_sec"),
            "end_sec": segment.get("end_sec"),
            "segment_summary": segment.get("segment_summary"),
            "observations": (segment.get("observations") or [])[:MAX_OBSERVATIONS_FOR_MERGE],
            "uncertainties": segment.get("uncertainties") or [],
            "error": segment.get("error"),
        })
    return json.dumps(trimmed, ensure_ascii=False, indent=1)


_HEADINGS = {
    "el": (
        "# Ανάλυση βίντεο",
        "## Επισκόπηση",
        "## Χρονολόγιο",
        "## Παρατηρήσεις ανά τμήμα",
        "## Αβεβαιότητες",
        "## Τμήματα που απέτυχαν",
    ),
    "en": (
        "# Video analysis",
        "## Overview",
        "## Timeline",
        "## Observations by segment",
        "## Uncertainties",
        "## Segments that failed",
    ),
}


def _detect_language(segments: list[dict]) -> str:
    """Majority vote across segments.

    One segment may be an English IDE screenshot, so taking the first segment's
    language would flip a Greek lecture's whole report to English.
    """
    votes: dict[str, int] = {}
    for segment in segments:
        code = str(segment.get("language") or "").strip().lower()
        if code in _HEADINGS:
            votes[code] = votes.get(code, 0) + 1
    if not votes:
        return "en"
    return max(votes.items(), key=lambda item: item[1])[0]


_LANGUAGE_NAMES = {"el": "Greek", "en": "English"}


def render_markdown(segments: list[dict]) -> str:
    """Build the report without the model, so there is always a result."""
    title, overview, timeline, by_seg, unsure, failed_h = _HEADINGS[_detect_language(segments)]
    lines = [title, ""]

    summaries = [s.get("segment_summary") for s in segments if s.get("segment_summary")]
    lines.append(overview)
    lines.append("")
    lines.extend(f"- {text}" for text in summaries) if summaries else lines.append("- (no summary produced)")
    lines.append("")

    lines.append(timeline)
    lines.append("")
    for segment in segments:
        for observation in segment.get("observations") or []:
            stamp = observation.get("timestamp") or ""
            description = (observation.get("description") or "").strip()
            if description:
                lines.append(f"- `[{stamp}]` {description}")
    lines.append("")

    lines.append(by_seg)
    lines.append("")
    for segment in segments:
        count = len(segment.get("observations") or [])
        lines.append(f"- **{segment.get('segment_id')}** "
                     f"({utils.hms(segment.get('start_sec') or 0)}ΞΒ²Ξ²β€Β¬Ξ²β‚¬Β{utils.hms(segment.get('end_sec') or 0)}): "
                     f"{count} observations")
    lines.append("")

    uncertainties = [u for s in segments for u in (s.get("uncertainties") or [])]
    lines.append(unsure)
    lines.append("")
    lines.extend(f"- {text}" for text in uncertainties) if uncertainties else lines.append("- none reported")
    lines.append("")

    failed = [s.get("segment_id") for s in segments if s.get("error")]
    if failed:
        lines.append(failed_h)
        lines.append("")
        lines.append(", ".join(failed))
        lines.append("")

    return "\n".join(lines)


def merge_results(results: list[dict], settings: Settings, client: DeepSeekClient) -> dict:
    ordered = sorted(results, key=lambda item: item.get("start_sec") or 0)

    language = _detect_language(ordered)
    markdown = ""
    try:
        prompt = (
            f"{load_prompt()}\n\n"
            f"Write the entire report in {_LANGUAGE_NAMES.get(language, 'English')} "
            f"({language}), matching the video's spoken and on-screen language.\n\n"
            f"Segment analyses (JSON):\n{_compact(ordered)}"
        )
        markdown = client.complete_text(prompt, max_tokens=3000).strip()
    except Exception as exc:  # noqa: BLE001 - the report must survive a merge failure
        logging.error("merge call failed: %s", exc)

    if len(markdown) < 50:
        logging.warning("model merge returned nothing usable; rendering the report locally")
        markdown = render_markdown(ordered)

    return {
        "segments": ordered,
        "failed_segments": [s["segment_id"] for s in ordered if s.get("error")],
        "markdown": markdown,
    }