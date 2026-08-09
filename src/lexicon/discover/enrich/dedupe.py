"""Dedupe raw field mentions across sources into one EnrichedField each.

Merge policy:
  - Key is normalized(name).lower() with punctuation stripped.
  - Canonical `name` is the first-seen casing.
  - `description` prefers the longer, more-detailed variant.
  - `sources` accumulates every mention.
Later enrichment stages populate unit / semantic_tags / traps.
"""
from __future__ import annotations
import re

from ..models import EnrichedField, RawField


_NORM = re.compile(r"[^A-Za-z0-9]+")


def _norm(name: str) -> str:
    return _NORM.sub("", name).lower()


def dedupe_raw_fields(raws: list[RawField]) -> list[EnrichedField]:
    by_key: dict[str, EnrichedField] = {}
    for r in raws:
        k = _norm(r.name)
        cur = by_key.get(k)
        if cur is None:
            by_key[k] = EnrichedField(
                name=r.name,
                description=r.description,
                sources=[r.source],
            )
        else:
            if len(r.description) > len(cur.description):
                cur.description = r.description
            cur.sources.append(r.source)
    return list(by_key.values())
