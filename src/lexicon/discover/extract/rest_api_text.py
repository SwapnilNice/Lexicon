"""Text-pattern extraction for REST/OpenAPI rendered HTML docs.

Handles the common pattern in vendor API references where fields appear as:

    field_name  type  —  description text

These docs are often JavaScript-rendered SPAs whose server-side HTML doesn't use
<table> or <dl> — so html_structured.py finds nothing. This extractor uses the
pre-cleaned doc.text (populated by the HTML fetcher) and matches the inline pattern.

Used as a fallback in the pipeline: only applied when html_structured returns empty.
"""
from __future__ import annotations
import re

from ..models import FieldSource, RawField, SourceDoc

_TYPE_WORDS = r"(?:string|integer|number|boolean|array|object|enum)"
_SEP = r"[—–\-]{1,2}"
_PATTERN = re.compile(
    rf"\b([a-z][a-z0-9_]{{2,60}})\s+{_TYPE_WORDS}[^—–\n]{{0,40}}{_SEP}\s+",
    re.UNICODE,
)
_STOP = frozenset({
    "string", "integer", "number", "boolean", "array", "object", "null",
    "format", "example", "default", "items", "required", "optional",
    "type", "true", "false", "none", "any",
})


def extract_rest_api_text(doc: SourceDoc) -> list[RawField]:
    # doc.text is already stripped/collapsed by the HTML fetcher (BeautifulSoup get_text)
    plain = doc.text or re.sub(r"<[^>]+>", " ", re.sub(r"\s+", " ", doc.content))
    matches = list(_PATTERN.finditer(plain))
    if not matches:
        return []

    out: list[RawField] = []
    for i, m in enumerate(matches):
        name = m.group(1)
        if name in _STOP:
            continue
        desc_start = m.end()
        desc_end = matches[i + 1].start() if i + 1 < len(matches) else desc_start + 300
        desc = re.sub(r"\s+", " ", plain[desc_start:desc_end]).strip()[:250]
        if len(desc) < 5:
            continue
        out.append(RawField(
            name=name,
            description=desc,
            source=FieldSource(
                doc_id=doc.id,
                url=doc.url,
                locator=f"text:char:{m.start()}",
                snippet=f"{name} — {desc[:120]}",
            ),
            extractor="rest_api_text",
            confidence_extraction=0.75,
        ))
    return out
