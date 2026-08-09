"""Markdown field extractor.

Recognizes vendor doc pages published as Markdown — typically AWS-style
`## <Heading>` blocks that contain an API metric identifier in backticks
somewhere within them (e.g. `ABANDONMENT_RATE`, `AGENTS_ON_CALL`).

Extraction pattern (proven against Amazon Connect metrics-definitions.md):

    ## Abandonment rate
    <a name="..."></a>

    This metric measures the percentage of abandoned contacts...

    **Metric type**: String
    ...
    **How to access using the Connect Customer API**:
    + [GetMetricDataV2](...) API: `ABANDONMENT_RATE`

Each ``## Heading`` becomes one candidate vendor field. The API id (the
SCREAMING_SNAKE_CASE token in backticks) is preferred as the field name
because that's what customers program against; the heading is folded into
the description. If no API id is present, the heading itself is the name.
"""
from __future__ import annotations
import re

from ..models import FieldSource, RawField, SourceDoc


# `## Heading` (with optional trailing whitespace); does NOT match `### sub`.
_H2_SPLIT = re.compile(r"^## (?!#)", re.MULTILINE)

# API metric identifier — SCREAMING_SNAKE_CASE token in backticks. Multiple
# fallback patterns (in decreasing specificity).
_API_ID_PATTERNS = [
    re.compile(r"API metric identifier:\s*`([A-Z][A-Z0-9_]{2,})`"),
    re.compile(r"API:\s*`([A-Z][A-Z0-9_]{2,})`"),
    re.compile(r"`([A-Z][A-Z0-9_]{3,})`"),
]

_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_INLINE_CODE = re.compile(r"`([^`]+)`")


def _first_meaningful_line(section_body: str) -> str:
    """First non-empty prose line after the heading — skips anchor tags,
    list markers, other structural noise. The section starts with the
    heading line itself, so we skip line 1 explicitly."""
    lines = section_body.splitlines()
    for line in lines[1:]:            # skip the heading (line 0)
        line = line.strip()
        if not line:
            continue
        if line.startswith(("<a name=", "<!--", "**", "+", "-", "#", "|")):
            continue
        return line
    return ""


def _find_api_id(section: str) -> str | None:
    for pat in _API_ID_PATTERNS:
        m = pat.search(section)
        if m:
            return m.group(1)
    return None


def _clean_prose(line: str) -> str:
    """Strip Markdown link syntax + inline code fences so the description reads cleanly."""
    line = _MD_LINK.sub(r"\1", line)
    line = _MD_INLINE_CODE.sub(r"\1", line)
    return line.strip()


def extract_markdown(doc: SourceDoc) -> list[RawField]:
    if doc.kind != "markdown":
        return []

    out: list[RawField] = []
    # Skip content before the first `## ` — that's usually the page intro.
    sections = _H2_SPLIT.split(doc.content)[1:]
    for i, section in enumerate(sections):
        # First line of the section IS the heading text.
        head_match = re.match(r"([^\n<]+)", section)
        if not head_match:
            continue
        heading = head_match.group(1).strip()
        api_id = _find_api_id(section)

        name = api_id or heading
        # Discard anything that clearly isn't a field identifier (very long, spaces, etc.)
        if not re.match(r"^[A-Za-z0-9_.\-\s]{1,80}$", name):
            continue

        desc_line = _clean_prose(_first_meaningful_line(section))
        # Truncate to a sentence-ish length.
        m_sent = re.match(r"(.{0,220}?[.!?])(?:\s|$)", desc_line)
        if m_sent:
            desc_line = m_sent.group(1)
        description = f"{heading}: {desc_line}" if api_id and desc_line else desc_line or heading

        out.append(RawField(
            name=name,
            description=description[:250],
            source=FieldSource(
                doc_id=doc.id,
                url=doc.url,
                locator=f"## {heading}",
                snippet=f"{heading} — {desc_line[:100]}",
            ),
            extractor="markdown",
            confidence_extraction=0.90,
        ))
    return out
