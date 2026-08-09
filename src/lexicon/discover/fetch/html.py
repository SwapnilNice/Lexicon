"""HTML source fetcher. Emits one SourceDoc per fetched page.

For v1 we do NOT implement multi-hop BFS crawling in the new pipeline;
that is the existing `src/discover.py` code path. v1 fetches the primary
URL only (`max_depth: 0`). Multi-hop crawl is a follow-up enhancement
(see follow-ups.md).
"""
from __future__ import annotations
import hashlib
import re
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
    html = body.decode("utf-8", errors="ignore")
    title, text = _extract_title_and_text(html)
    doc_id = f"html:{hashlib.sha256(source.url.encode()).hexdigest()[:12]}"
    return [SourceDoc(
        id=doc_id, kind="html", url=source.url,
        title=title, content=html, text=text,
    )]
