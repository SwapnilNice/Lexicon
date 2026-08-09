"""Trap detection. Looks for phrasings and unit mismatches that flag
known semantic risks:

  - exclusion: "does NOT include X" / "excludes X"    (e.g. Avaya acdtime)
  - inclusion: "includes X" / "combined with X"       (e.g. Genesys tHandle)
  - unit_slip: this field's unit differs from its peer group's

The mapper (Task 18) reads these traps to inform compositional formulas.
"""
from __future__ import annotations
import re
from collections import Counter

from ..models import EnrichedField, Trap


EXCLUDE_RE = re.compile(
    r"(?:does not include|doesn't include|excludes?|excluding)\s+([A-Za-z_][\w\s]{0,40})",
    re.IGNORECASE,
)
INCLUDE_RE = re.compile(
    r"(?:includes?|combined with|including)\s+([A-Za-z_][\w\s]{0,40})",
    re.IGNORECASE,
)


_TARGET_CANONICAL = {
    "hold": "hold_time",
    "holdtime": "hold_time",
    "acw": "acw_time",
    "wrapup": "acw_time",
    "wrap": "acw_time",
    "wrap-up": "acw_time",
    "after-call": "acw_time",
    "aftercall": "acw_time",
    "talk": "talk_time",
    "talktime": "talk_time",
}


def _target_of(mention: str) -> str:
    key = re.split(r"\s+", mention.lower())[0].strip(".,;:")
    return _TARGET_CANONICAL.get(key, key)


def _detect_phrase_traps(field: EnrichedField) -> None:
    for m in EXCLUDE_RE.finditer(field.description):
        field.traps.append(Trap(
            kind="exclusion",
            target=_target_of(m.group(1)),
            evidence=m.group(0),
        ))
    for m in INCLUDE_RE.finditer(field.description):
        field.traps.append(Trap(
            kind="inclusion",
            target=_target_of(m.group(1)),
            evidence=m.group(0),
        ))


def _detect_unit_slip(fields: list[EnrichedField]) -> None:
    duration_units = [f.unit for f in fields if f.unit.startswith("duration_")]
    if not duration_units:
        return
    counter = Counter(duration_units)
    if len(counter) < 2:
        return
    majority = counter.most_common(1)[0][0]
    for f in fields:
        if f.unit.startswith("duration_") and f.unit != majority:
            f.traps.append(Trap(
                kind="unit_slip",
                target=majority,
                evidence=f"peer group is {majority}, this field is {f.unit}",
            ))


def detect_traps(fields: list[EnrichedField]) -> None:
    for f in fields:
        _detect_phrase_traps(f)
    _detect_unit_slip(fields)
