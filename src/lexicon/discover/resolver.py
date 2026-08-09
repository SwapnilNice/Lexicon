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

import yaml

from .llm import LLMClient
from .models import RegistrySource, VendorRegistryEntry
from .validation import validate_slug


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


# ---------------------------------------------------------------------------
# Task 8 – search fallback for unknown vendors
# ---------------------------------------------------------------------------


SEARCH_PROMPT_TEMPLATE = """You are helping locate authoritative documentation for an ACD/contact-center system.

The ACD system is: "{vendor}"

Return a YAML document with these fields:
  slug: <lower_snake_case identifier for this vendor>
  name: <human-readable name>
  sources:
    - kind: html_doc
      role: primary
      url: <best URL for the vendor's primary developer/admin documentation>
    - kind: html_doc
      role: secondary
      url: <optional additional URL — community/support article, WSDL landing page, etc.>

Rules:
- Include URLs on the vendor's own domains only. Authoritative sources may live at:
  * docs.*, developer.*, api.*, help.*, admin.* — official documentation
  * community.*, success.*, trailhead.* — vendor community sites (often hold API/WSDL
    references and integration notes that official docs miss; treat them as valid sources)
  * support.*, kb.* — support knowledge bases with integration articles
- Prefer pages that document data models, historical reporting fields, or API schemas.
- If the same information appears on both official docs and a community article, prefer
  the official one — but a community URL is a valid primary source when official docs
  don't cover the topic (common for integration/WSDL/webhook references).
- If unsure, include a best-guess URL as primary + one alternate as secondary.
- Return YAML ONLY — no prose, no code fences.
"""


def resolve_vendor_with_fallback(
    query: str,
    registry: list[VendorRegistryEntry],
    llm: LLMClient,
) -> ResolveResult:
    try:
        return resolve_vendor(query, registry)
    except ResolveError as e:
        if "no match" not in str(e):
            raise  # ambiguity is not a search-fallback situation
    text = llm.complete(
        model="claude-sonnet-4-6",
        prompt=SEARCH_PROMPT_TEMPLATE.format(vendor=query),
    )
    data = yaml.safe_load(text) or {}
    if "slug" not in data or "sources" not in data:
        raise ResolveError(
            f"search fallback for '{query}' returned invalid YAML: {text[:200]!r}"
        )
    try:
        validate_slug(data["slug"], f"search fallback for '{query}'")
    except ValueError as exc:
        raise ResolveError(str(exc)) from exc
    sources = [
        RegistrySource(
            kind=s.get("kind", "html_doc"),
            role=s.get("role", "primary"),
            url=s.get("url"),
            crawl=s.get("crawl", {}),
        )
        for s in data["sources"]
    ]
    entry = VendorRegistryEntry(
        slug=data["slug"],
        name=data.get("name", query),
        aliases=data.get("aliases", []),
        category="fixed_schema",
        description=f"Discovered via search fallback for query '{query}'.",
        sources=sources,
    )
    return ResolveResult(entry=entry, resolved_via="search")
