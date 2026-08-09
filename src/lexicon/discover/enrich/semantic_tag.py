"""Semantic tagging: label each enriched field with the canonical concept
families it looks like (talk_time_like, hold_time_like, ready_time_like, …).

Deliberately rule-based. The keyword lexicon is loaded from
`ontology/discover_lexicon.yaml` — framework code contains ZERO vendor
tokens. Adding a vendor is a YAML edit, not a source change.
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import re

import yaml

from ..models import EnrichedField, SemanticTag


_LEXICON_PATH = Path(__file__).resolve().parents[4] / "ontology" / "discover_lexicon.yaml"


@lru_cache(maxsize=1)
def _load_tag_keywords() -> dict[str, set[str]]:
    """Load and cache the tag keyword lexicon.

    Reads from `ontology/discover_lexicon.yaml`. Returns a dict mapping each
    canonical concept family (e.g. `talk_time_like`) to a set of keyword
    tokens used for matching. Tokens themselves are vendor-specific
    identifiers (documented in the YAML file) but they are ONLY used as
    match keys — they are never emitted into any output artifact.
    """
    raw = yaml.safe_load(_LEXICON_PATH.read_text()) or {}
    tag_kw = raw.get("tag_keywords") or {}
    return {tag: set(keywords) for tag, keywords in tag_kw.items()}


# Public read-only accessor for the loaded lexicon.
# (kept as a callable so tests can inspect it without a global mutable.)
def TAG_LEXICON() -> dict[str, set[str]]:                  # noqa: N802 — public API
    return _load_tag_keywords()


_TOKEN_RE = re.compile(r"[^A-Za-z]+")


def _tokens(name: str, desc: str) -> set[str]:
    parts = _TOKEN_RE.split(name.lower())
    parts += _TOKEN_RE.split(desc.lower())
    return {p for p in parts if p}


def _score_tag(keywords: set[str], name: str, desc: str, toks: set[str]) -> float:
    name_l = name.lower()
    substr = sum(1 for kw in keywords if len(kw) >= 4 and kw in name_l)
    token = len(keywords & toks)
    if substr == 0 and token == 0:
        return 0.0
    raw = 3 * substr + token
    return min(1.0, raw / 5.0)


def tag_fields(fields: list[EnrichedField]) -> None:
    lexicon = _load_tag_keywords()
    for f in fields:
        toks = _tokens(f.name, f.description)
        for tag, kws in lexicon.items():
            s = _score_tag(kws, f.name, f.description, toks)
            if s >= 0.4:
                f.semantic_tags.append(SemanticTag(
                    tag=tag,
                    weight=s,
                    rationale=f"keyword lexicon match (score={s:.2f})",
                ))
