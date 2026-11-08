"""Counters for citation quality, persisted to a small JSON file.

Why this exists: the value of a video Q&A product is whether a jump link lands on
the moment it promises. Two numbers decide that -- how many answers carry at
least one validated citation, and how many citations the model invented (which
the backend had to drop). Without them a prompt change is unmeasurable.

Deliberately a single small JSON file rather than a metrics stack: this is a
local single-process app. Every write is behind one lock and the whole snapshot
is rewritten, which is fine at this volume and keeps the file readable.
"""

import json
import threading
from pathlib import Path

_LOCK = threading.Lock()
_PATH = Path(__file__).resolve().parent / "metrics.json"

_DEFAULTS = {
    "answers": 0,
    "answers_with_citation": 0,
    "markers_kept": 0,
    "markers_dropped": 0,
    "fallback_citations": 0,
    "citation_clicks": 0,
}


def _load() -> dict:
    try:
        with open(_PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return dict(_DEFAULTS)
    merged = dict(_DEFAULTS)
    if isinstance(stored, dict):
        for key in _DEFAULTS:
            value = stored.get(key)
            if isinstance(value, (int, float)):
                merged[key] = int(value)
    return merged


def _save(data: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-replace so a crash mid-write cannot truncate the counters.
        temporary = _PATH.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(_PATH)
    except OSError:
        pass


def bump(field: str, amount: int = 1) -> None:
    if field not in _DEFAULTS:
        raise ValueError(f"unknown metric: {field}")
    with _LOCK:
        data = _load()
        data[field] = data.get(field, 0) + int(amount)
        _save(data)


def record_answer(markers_kept: int, markers_dropped: int, used_fallback: bool) -> None:
    """Book one answered question and what happened to its citations."""
    with _LOCK:
        data = _load()
        data["answers"] += 1
        if markers_kept > 0:
            data["answers_with_citation"] += 1
        data["markers_kept"] += int(markers_kept)
        data["markers_dropped"] += int(markers_dropped)
        if used_fallback:
            data["fallback_citations"] += 1
        _save(data)


def snapshot() -> dict:
    with _LOCK:
        data = _load()

    answers = data["answers"]
    tried = data["markers_kept"] + data["markers_dropped"]
    return {
        **data,
        # The two ratios worth watching: the share of answers a user can jump
        # from, and the share of the model's timestamps that pointed at an
        # excerpt it was actually given.
        "answers_with_citation_pct": round(100.0 * data["answers_with_citation"] / answers, 1)
        if answers
        else 0.0,
        "marker_validity_pct": round(100.0 * data["markers_kept"] / tried, 1) if tried else 0.0,
        "citation_clicks_per_answer": round(data["citation_clicks"] / answers, 2)
        if answers
        else 0.0,
    }
