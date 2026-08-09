"""Vendor-name → registry entry resolution.

Rules (all case-insensitive):
  1. Exact match against slug (highest priority)
  2. Exact match against name
  3. Case-insensitive alias match
  4. Ambiguity (>1 match) → fail with candidate list
  5. No match → fail; search fallback (Task 8) handles this
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from .models import VendorRegistryEntry


ResolveVia = Literal["slug", "name", "alias", "search"]


@dataclass
class ResolveResult:
    entry: VendorRegistryEntry
    resolved_via: ResolveVia


class ResolveError(ValueError):
    pass


def resolve_vendor(query: str, entries: list[VendorRegistryEntry]) -> ResolveResult:
    q = query.strip().lower()
    slug_hits = [e for e in entries if e.slug.lower() == q]
    if len(slug_hits) == 1:
        return ResolveResult(entry=slug_hits[0], resolved_via="slug")

    name_hits = [e for e in entries if e.name.lower() == q]
    if len(name_hits) == 1:
        return ResolveResult(entry=name_hits[0], resolved_via="name")

    alias_hits = [
        e for e in entries
        if q in (a.lower() for a in e.aliases)
    ]
    if len(alias_hits) == 1:
        return ResolveResult(entry=alias_hits[0], resolved_via="alias")

    all_hits = {e.slug: e for e in slug_hits + name_hits + alias_hits}
    if len(all_hits) > 1:
        candidates = ", ".join(sorted(all_hits))
        raise ResolveError(
            f"'{query}' is ambiguous; candidates: {candidates}. "
            f"Invoke by slug: lexicon discover <slug>"
        )

    raise ResolveError(f"no match for '{query}' in registry")
