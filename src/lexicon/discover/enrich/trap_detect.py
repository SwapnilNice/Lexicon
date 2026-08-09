"""Trap detection. Looks for phrasings and unit mismatches that flag
known semantic risks:

  - exclusion: "does NOT include X" / "excludes X"
  - inclusion: "includes X" / "combined with X"
  - unit_slip: this field's unit differs from its peer group's

The mapper reads these traps to inform compositional formulas. The
`canonical_target_map` used to normalize free-text concept mentions
to canonical slugs lives in ontology/discover_lexicon.yaml so framework
code contains no vendor tokens.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import re
from collections import Counter

import yaml

from ..models import EnrichedField, Trap


EXCLUDE_RE = re.compile(
    r"(?:does not include|doesn't include|excludes?|excluding)\s+([A-Za-z_][\w\s]{0,40})",
    re.IGNORECASE,
)
INCLUDE_RE = re.compile(
    r"(?:includes?|combined with|including)\s+([A-Za-z_][\w\s]{0,40})",
    re.IGNORECASE,
)


_LEXICON_PATH = Path(__file__).resolve().parents[4] / "ontology" / "discover_lexicon.yaml"


@lru_cache(maxsize=1)
def _load_canonical_target_map() -> dict[str, str]:
    raw = yaml.safe_load(_LEXICON_PATH.read_text()) or {}
    return dict(raw.get("canonical_target_map") or {})


def _target_of(mention: str) -> str:
    key = re.split(r"\s+", mention.lower())[0].strip(".,;:")
    return _load_canonical_target_map().get(key, key)


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
