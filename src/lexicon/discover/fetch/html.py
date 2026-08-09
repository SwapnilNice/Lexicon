"""HTML source fetcher. Emits one SourceDoc per fetched page.

For v1 we do NOT implement multi-hop BFS crawling in the new pipeline;
that is the existing `src/discover.py` code path. v1 fetches the primary
URL only (`max_depth: 0`). Multi-hop crawl is a follow-up enhancement
(see follow-ups.md).
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup
import httpx

from ..cache import DiskCache
from ..models import RegistrySource, SourceDoc


def _default_fetcher(url: str) -> bytes:
    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": "Lexicon-discover/1.0"})
    r.raise_for_status()
    return r.content


def _extract_title_and_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    for bad in soup(["script", "style"]):
        bad.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return title, text


def _looks_like_markdown(url: str, content: str) -> bool:
    """Heuristic: is this content Markdown rather than HTML?

    Signals:
      - URL ends in `.md`
      - Content has no `<html>` / `<body>` tags but does have `## ` heading lines
    """
    if url.endswith(".md"):
        return True
    stripped = content.lstrip()
    if stripped.startswith("<"):
        return False   # HTML-ish document
    has_h2 = bool(re.search(r"^##\s", stripped, re.MULTILINE))
    return has_h2


def _looks_like_pdf(url: str, body: bytes) -> bool:
    """Is the raw body a PDF?"""
    return url.lower().endswith(".pdf") or body[:5] == b"%PDF-"


def _pdf_to_markdown(body: bytes) -> str:
    """Extract text from a PDF and coerce it into a Markdown-ish shape.

    Each page becomes a `## Page N` section. Lines that look like field
    definitions (short capitalized identifier followed by longer prose)
    get promoted to `## <identifier>` headings so the Markdown extractor
    can pick them up.
    """
    import io
    try:
        import pypdf
    except ImportError as e:
        raise RuntimeError("pypdf not installed — required for PDF sources") from e

    reader = pypdf.PdfReader(io.BytesIO(body))
    parts: list[str] = []
    parts.append(f"# {reader.metadata.title if reader.metadata and reader.metadata.title else 'PDF'}\n")

    # Field-definition patterns — tried in order. Each captures (name, description).
    # Order matters: more specific / more punctuation-anchored first.
    patterns = [
        # "Field Name: description" or "Field Name - description" or "Field Name – description" (en dash)
        re.compile(r"^([A-Z][A-Za-z0-9 _./&-]{2,60})\s*[:\-–]\s+(.{20,})$"),
        # "Field Name (subtype description) rest of description"  ← Five9 style
        re.compile(r"^([A-Z][A-Za-z ]{2,50})\s*\(([^)]{3,60})\)\s+(.{20,})$"),
        # "AVG_HANDLE_TIME  description" (SNAKE_CASE + gap + text)
        re.compile(r"^([A-Z][A-Z0-9_]{4,50})\s{2,}(.{20,})$"),
    ]
    noise_prefixes = (
        "Page ",                       # page numbers in headers
        "Cloud Contact Center",        # vendor footer
        "Dashboards and Reports",      # section header
        "Administrator",               # section header
    )

    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        if not text.strip():
            continue

        promoted_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                promoted_lines.append("")
                continue

            # Drop obvious page/section header noise
            if any(stripped.startswith(p) for p in noise_prefixes):
                continue
            if len(stripped) < 5:      # single-digit page numbers, section markers
                continue

            matched = False
            for pat in patterns:
                m = pat.match(stripped)
                if not m:
                    continue
                name = m.group(1).strip()
                # Description is the LAST group (patterns[1] has a subtype in the middle).
                description = m.group(m.lastindex).strip()
                # Reject if the "name" looks like a run-on sentence
                if len(name.split()) > 6:
                    continue
                promoted_lines.append(f"\n## {name}")
                promoted_lines.append(description)
                matched = True
                break

            if not matched:
                promoted_lines.append(stripped)

        parts.append("\n".join(promoted_lines))

    return "\n".join(parts)


def _markdown_title(md: str) -> str:
    """First `# Title` heading in the document, or empty string."""
    m = re.search(r"^#\s+(.+)$", md, re.MULTILINE)
    return m.group(1).strip() if m else ""


def fetch_html_source(
    source: RegistrySource,
    *,
    cache: DiskCache,
    _fetcher: Callable[[str], bytes] | None = None,
) -> list[SourceDoc]:
    if source.url is None:
        return []
    fetcher = _fetcher or _default_fetcher
    body = cache.get("http", source.url)
    if body is None:
        if cache.offline:
            raise RuntimeError(
                f"offline cache miss for {source.url!r}; "
                "populate the cache before running in offline mode"
            )
        body = fetcher(source.url)
        cache.put("http", source.url, body)
    # PDF path — extract text, promote likely field headings, emit as markdown.
    if _looks_like_pdf(source.url, body):
        md_content = _pdf_to_markdown(body)
        doc_id = f"pdf:{hashlib.sha256(source.url.encode()).hexdigest()[:12]}"
        return [SourceDoc(
            id=doc_id, kind="markdown", url=source.url,
            title=_markdown_title(md_content) or Path(source.url).stem,
            content=md_content,
            text="",
        )]

    content = body.decode("utf-8", errors="ignore")

    if _looks_like_markdown(source.url, content):
        doc_id = f"md:{hashlib.sha256(source.url.encode()).hexdigest()[:12]}"
        return [SourceDoc(
            id=doc_id, kind="markdown", url=source.url,
            title=_markdown_title(content),
            content=content,
            text="",
        )]

    title, text = _extract_title_and_text(content)
    doc_id = f"html:{hashlib.sha256(source.url.encode()).hexdigest()[:12]}"
    return [SourceDoc(
        id=doc_id, kind="html", url=source.url,
        title=title, content=content, text=text,
    )]
