"""Unit inference for enriched fields.

Signals (cheapest → costliest), each contributes to unit_confidence:

  1. Name suffix (`*_ms`, `*Pct`, `n<Name>`, `*_count`, `*_seconds`)
  2. OpenAPI x-unit / format text surfaced by extract/openapi.py
  3. Description regex ("in milliseconds", "seconds", "percent", "count of")
  4. (LLM classifier: stub for v1 — the three signals above cover both
     anchor vendors. Add later if a real vendor forces it.)
"""
from __future__ import annotations
import re

from ..models import EnrichedField


NAME_MS = re.compile(r"(_ms$|Ms$|_millis|_MS$)", re.IGNORECASE)
NAME_SEC = re.compile(r"(_seconds?$|_sec$|time$)", re.IGNORECASE)
NAME_PCT = re.compile(r"(pct$|percent$|_percent$|_rate$)", re.IGNORECASE)
NAME_COUNT = re.compile(r"^n[A-Z]|_count$|count$|^sum_|^num_", re.IGNORECASE)

DESC_MS = re.compile(r"\b(?:in\s+)?milliseconds\b", re.I)
DESC_SEC = re.compile(r"\b(?:in\s+)?seconds\b", re.I)
DESC_PCT = re.compile(r"\bpercent(?:age)?\b", re.I)
DESC_COUNT = re.compile(r"\bcount\b|\bnumber of\b", re.I)


def _score(field: EnrichedField):
    signals: list[str] = []
    scores = {"duration_ms": 0.0, "duration_seconds": 0.0, "percentage": 0.0, "count": 0.0}
    name = field.name
    desc = field.description

    if NAME_MS.search(name):
        scores["duration_ms"] += 0.9; signals.append("name_suffix:ms")
    if NAME_SEC.search(name):
        scores["duration_seconds"] += 0.6; signals.append("name_suffix:seconds")
    if NAME_PCT.search(name):
        scores["percentage"] += 0.9; signals.append("name_suffix:pct")
    if NAME_COUNT.search(name):
        scores["count"] += 0.6; signals.append("name_suffix:count")

    if DESC_MS.search(desc):
        scores["duration_ms"] += 0.85; signals.append("description_regex:ms")
        if "(unit:" in desc and "millisec" in desc.lower():
            signals.append("x-unit:milliseconds")
    if DESC_SEC.search(desc) and not DESC_MS.search(desc):
        scores["duration_seconds"] += 0.7; signals.append("description_regex:seconds")
    if DESC_PCT.search(desc):
        scores["percentage"] += 0.7; signals.append("description_regex:pct")
    if DESC_COUNT.search(desc):
        scores["count"] += 0.5; signals.append("description_regex:count")

    best = max(scores.items(), key=lambda kv: kv[1])
    unit, conf = best
    if conf < 0.3:
        return "unknown", 0.0, signals
    return unit, min(conf, 0.98), signals


def infer_units(fields: list[EnrichedField]) -> None:
    for f in fields:
        unit, conf, signals = _score(f)
        f.unit = unit
        f.unit_confidence = conf
        f.unit_signals = signals
