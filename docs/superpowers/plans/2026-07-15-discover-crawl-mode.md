# discover.py Crawl Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--crawl` mode to `src/discover.py` that walks a vendor documentation site from a seed URL and produces the same `fixtures/vendor_catalogs/<vendor>.yaml` shape as today's `--doc`/`--from-csv` modes.

**Architecture:** New helpers inside `src/discover.py` — URL canonicalization/slugging, a bounded same-host BFS crawler, a disk cache under `fixtures/vendor_docs/<vendor>/`, and a chunk-merge extractor that runs the existing `fields_from_text_llm` per ~10 000-char chunk. CLI grows four flags (`--crawl`, `--max-depth`, `--max-pages`, `--refresh`); nothing outside `src/discover.py` changes.

**Tech Stack:** Python 3, stdlib only (`urllib.request`, `urllib.parse`, `urllib.robotparser`, `http.server` for tests, `pathlib`, `re`, `time`), plus existing `yaml` + optional `anthropic` SDK the file already uses. Tests use `pytest` and monkey-patching.

**Repo note (this environment):** This directory is not a git repo (`git rev-parse` fails). Standard `git add`/`git commit` steps are **omitted** — treat "green pytest" as the checkpoint after each task. If you later `git init`, re-introduce the commits at the natural task boundaries.

**Reference:** [`docs/superpowers/specs/2026-07-15-discover-crawl-mode-design.md`](../specs/2026-07-15-discover-crawl-mode-design.md)

**Ground rules (from `CLAUDE.md`):** After code changes, `pytest -v` must be green. The sensor gate does not apply to this feature (it does not produce output XML), but the existing tests must not regress.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/discover.py` | Modify | Add functions `_canonical_url`, `_slugify_url`, `_fetch_one`, `_load_robots`, `_extract_links`, `_chunk_text`, `crawl_site`, `fields_from_pages_llm`. Extend `main()` CLI. |
| `tests/test_discover_crawl.py` | Create | Unit + integration tests for the new functions and end-to-end crawl → YAML. |
| `fixtures/vendor_docs/` | Create (runtime) | Per-vendor page cache. Created lazily by `crawl_site`. |
| `.gitignore` | Create-or-modify | Add `fixtures/vendor_docs/` so cached pages aren't checked in if git is later initialized. |
| `README.md` | Modify | One new usage example under the discover section. |

`automap.py`, `engine.py`, `sensor.py`, ontology YAML, and existing catalogs are **not touched**.

---

## Task 1: Test scaffolding + URL helpers (`_canonical_url`, `_slugify_url`)

**Files:**
- Create: `tests/test_discover_crawl.py`
- Modify: `src/discover.py` (add helpers)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_discover_crawl.py` (new file):

```python
"""Tests for the --crawl mode of src/discover.py."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import discover  # noqa: E402


def test_canonical_url_strips_fragment_and_lowercases_host():
    assert discover._canonical_url("HTTPS://Docs.Example.COM/a/b#section") == \
        "https://docs.example.com/a/b"


def test_canonical_url_normalizes_trailing_slash():
    # Root path keeps its slash; non-root paths drop it.
    assert discover._canonical_url("https://x.example.com/") == "https://x.example.com/"
    assert discover._canonical_url("https://x.example.com/foo/") == "https://x.example.com/foo"


def test_slugify_url_is_deterministic_and_bounded():
    slug1 = discover._slugify_url("https://docs.example.com/a/b?c=1")
    slug2 = discover._slugify_url("https://docs.example.com/a/b?c=1")
    assert slug1 == slug2
    assert len(slug1) <= 120
    assert set(slug1) <= set("abcdefghijklmnopqrstuvwxyz0123456789_.-")


def test_slugify_url_distinguishes_different_urls():
    assert discover._slugify_url("https://docs.example.com/a") != \
        discover._slugify_url("https://docs.example.com/b")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: FAIL — `AttributeError: module 'discover' has no attribute '_canonical_url'`.

- [ ] **Step 3: Implement the helpers**

Add these imports near the top of `src/discover.py` (keep existing imports):

```python
import time
import urllib.parse
import urllib.robotparser
```

Add these functions to `src/discover.py` (after the existing `strip_html`/`pdf_text` helpers, before `fields_from_csv`):

```python
def _canonical_url(url: str) -> str:
    """Strip fragment, lowercase host, drop trailing slash on non-root paths."""
    p = urllib.parse.urlparse(url)
    host = p.netloc.lower()
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urllib.parse.urlunparse((p.scheme.lower(), host, path, p.params, p.query, ""))


def _slugify_url(url: str) -> str:
    """Deterministic filesystem-safe slug for a URL. Bounded at 120 chars."""
    p = urllib.parse.urlparse(url)
    raw = f"{p.netloc}{p.path}"
    if p.query:
        raw += f"_{p.query}"
    slug = re.sub(r"[^a-z0-9._-]+", "_", raw.lower()).strip("_") or "root"
    return slug[:120]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 4 passed.

Run: `pytest -v`
Expected: full suite still passes (baseline + new tests).

---

## Task 2: `_fetch_one` (single HTTP fetch) + `_extract_links`

**Files:**
- Modify: `src/discover.py` (add `_fetch_one`, `_extract_links`)
- Modify: `tests/test_discover_crawl.py` (append tests + a local HTTP server fixture)

- [ ] **Step 1: Write failing tests + fixture**

Append to `tests/test_discover_crawl.py`:

```python
import http.server
import threading
import pytest


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves paths from the class-level ROUTES dict. Silences logging."""
    ROUTES: dict = {}

    def do_GET(self):  # noqa: N802
        route = self.ROUTES.get(self.path)
        if route is None:
            self.send_response(404); self.end_headers(); return
        body, ctype = route
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a, **_kw):
        pass  # silent


@pytest.fixture
def http_server():
    """Start a threaded HTTP server on a random port; yield (base_url, routes)."""
    _Handler.ROUTES = {}
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}", _Handler.ROUTES
    srv.shutdown(); srv.server_close()


def test_fetch_one_returns_body_and_content_type(http_server):
    base, routes = http_server
    routes["/hello"] = (b"<html>hi</html>", "text/html; charset=utf-8")
    body, ctype = discover._fetch_one(f"{base}/hello")
    assert body == b"<html>hi</html>"
    assert "text/html" in ctype


def test_fetch_one_raises_on_404(http_server):
    base, _ = http_server
    with pytest.raises(Exception):
        discover._fetch_one(f"{base}/missing")


def test_extract_links_finds_href_and_resolves_relative():
    html = '<a href="/next">A</a> <a href="https://other.example.com/x">B</a>'
    links = discover._extract_links(html, "https://docs.example.com/a/b")
    assert "https://docs.example.com/next" in links
    assert "https://other.example.com/x" in links


def test_extract_links_ignores_javascript_and_mailto():
    html = '<a href="javascript:void(0)">X</a> <a href="mailto:x@y">Y</a> <a href="/ok">Z</a>'
    links = discover._extract_links(html, "https://docs.example.com/")
    assert links == ["https://docs.example.com/ok"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 4 new tests FAIL — `_fetch_one` / `_extract_links` don't exist yet.

- [ ] **Step 3: Implement**

Add to `src/discover.py` (after `_slugify_url`):

```python
USER_AGENT = "Lexicon-discover/1.0"


def _fetch_one(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Fetch a single URL. Returns (body_bytes, content_type). Raises on non-2xx."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        ctype = r.headers.get("Content-Type", "").lower()
    return body, ctype


_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def _extract_links(html: str, base_url: str) -> list[str]:
    """Regex link extraction. Drops mailto/javascript/anchor-only, resolves relative."""
    out = []
    for raw in _HREF_RE.findall(html):
        raw = raw.strip()
        if not raw or raw.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        out.append(urllib.parse.urljoin(base_url, raw))
    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 8 passed (4 old + 4 new).

---

## Task 3: `_chunk_text` and merge rule

**Files:**
- Modify: `src/discover.py` (add `_chunk_text`, `_merge_field_maps`)
- Modify: `tests/test_discover_crawl.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_discover_crawl.py`:

```python
def test_chunk_text_splits_on_paragraph_boundary():
    text = ("A" * 4000) + "\n\n" + ("B" * 4000) + "\n\n" + ("C" * 4000)
    chunks = discover._chunk_text(text, size=5000)
    # Should split into 3 chunks, each starting on a paragraph.
    assert len(chunks) == 3
    assert chunks[0].startswith("A") and chunks[1].startswith("B") and chunks[2].startswith("C")


def test_chunk_text_returns_single_chunk_when_small():
    assert discover._chunk_text("short text", size=10_000) == ["short text"]


def test_merge_field_maps_prefers_longer_description():
    a = {"acdtime": "Talk time.", "holdtime": ""}
    b = {"acdtime": "Talk time of ACD calls, in seconds.", "holdtime": "Hold time in seconds."}
    merged = discover._merge_field_maps(a, b)
    assert merged["acdtime"] == "Talk time of ACD calls, in seconds."
    assert merged["holdtime"] == "Hold time in seconds."


def test_merge_field_maps_never_overwrites_nonempty_with_empty():
    a = {"acdtime": "Talk time."}
    b = {"acdtime": ""}
    assert discover._merge_field_maps(a, b) == {"acdtime": "Talk time."}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 4 new tests FAIL.

- [ ] **Step 3: Implement**

Add to `src/discover.py` (after `_extract_links`):

```python
def _chunk_text(text: str, size: int = 10_000) -> list[str]:
    """Split on paragraph boundaries into pieces close to `size` chars."""
    if len(text) <= size:
        return [text]
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) + 2 > size:
            chunks.append(buf); buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def _merge_field_maps(a: dict, b: dict) -> dict:
    """Merge two {name: description} dicts. Non-empty wins over empty; longer wins."""
    out = dict(a)
    for name, desc in b.items():
        cur = out.get(name, "")
        if not cur and desc:
            out[name] = desc
        elif desc and len(desc) > len(cur):
            out[name] = desc
    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 12 passed.

---

## Task 4: `_load_robots` (testable robots.txt shim)

**Files:**
- Modify: `src/discover.py`
- Modify: `tests/test_discover_crawl.py`

Rationale: `crawl_site` needs a robots.txt check. To keep the crawler test-friendly we route the robots parser through a tiny helper that tests can monkey-patch, instead of letting `urllib.robotparser` do its own network fetch inside the crawl.

- [ ] **Step 1: Write failing test**

Append to `tests/test_discover_crawl.py`:

```python
def test_load_robots_returns_parser_that_disallows_declared_paths(http_server):
    base, routes = http_server
    routes["/robots.txt"] = (b"User-agent: *\nDisallow: /private/\n", "text/plain")
    rp = discover._load_robots(base)
    assert rp.can_fetch(discover.USER_AGENT, f"{base}/public") is True
    assert rp.can_fetch(discover.USER_AGENT, f"{base}/private/x") is False
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_discover_crawl.py::test_load_robots_returns_parser_that_disallows_declared_paths -v`
Expected: FAIL — `_load_robots` not defined.

- [ ] **Step 3: Implement**

Add to `src/discover.py` (after `_merge_field_maps`):

```python
def _load_robots(site_root: str) -> urllib.robotparser.RobotFileParser:
    """Load and parse robots.txt for the given site root. Errors -> permissive parser."""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(urllib.parse.urljoin(site_root, "/robots.txt"))
    try:
        rp.read()
    except Exception:  # noqa: BLE001
        pass  # missing robots.txt = allow everything
    return rp
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 13 passed.

---

## Task 5: `crawl_site` — core BFS (bounds + host + dedup)

**Files:**
- Modify: `src/discover.py` (add `crawl_site`)
- Modify: `tests/test_discover_crawl.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_discover_crawl.py`:

```python
def _pages_with_chain(n):
    """Return a routes dict of /p0 -> /p1 -> ... -> /p{n-1}, each an HTML page."""
    routes = {}
    for i in range(n):
        nxt = f'<a href="/p{i+1}">next</a>' if i + 1 < n else ""
        routes[f"/p{i}"] = (f"<html>page {i} {nxt}</html>".encode(), "text/html")
    return routes


def test_crawl_stops_at_max_pages(http_server, tmp_path):
    base, routes = http_server
    routes.update(_pages_with_chain(50))
    pages = discover.crawl_site(f"{base}/p0", max_depth=99, max_pages=10,
                                cache_dir=tmp_path, refresh=True)
    assert len(pages) == 10
    # Each item is (url, path).
    assert all(url.startswith(base) for url, _ in pages)


def test_crawl_stops_at_max_depth(http_server, tmp_path):
    base, routes = http_server
    routes.update(_pages_with_chain(10))
    pages = discover.crawl_site(f"{base}/p0", max_depth=1, max_pages=99,
                                cache_dir=tmp_path, refresh=True)
    # depth=0: /p0. depth=1: /p1. That's it.
    assert len(pages) == 2


def test_crawl_stays_on_host(http_server, tmp_path):
    base, routes = http_server
    routes["/seed"] = (b'<a href="/local">L</a> <a href="https://other.example.com/x">X</a>',
                       "text/html")
    routes["/local"] = (b"<html>local</html>", "text/html")
    pages = discover.crawl_site(f"{base}/seed", max_depth=2, max_pages=99,
                                cache_dir=tmp_path, refresh=True)
    # Only /seed and /local; other.example.com must not be fetched.
    assert len(pages) == 2
    assert all("other.example.com" not in url for url, _ in pages)


def test_crawl_dedups_by_canonical_url(http_server, tmp_path):
    base, routes = http_server
    routes["/seed"] = (b'<a href="/x#a">a</a> <a href="/x#b">b</a> <a href="/x/">c</a>',
                       "text/html")
    routes["/x"] = (b"<html>x</html>", "text/html")
    pages = discover.crawl_site(f"{base}/seed", max_depth=2, max_pages=99,
                                cache_dir=tmp_path, refresh=True)
    # /seed + /x (once) — fragments and trailing slash collapse to same canonical URL.
    assert len(pages) == 2
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 4 new tests FAIL — `crawl_site` not defined.

- [ ] **Step 3: Implement**

Add to `src/discover.py` (after `_load_robots`):

```python
def crawl_site(seed: str, max_depth: int, max_pages: int,
               cache_dir: pathlib.Path, refresh: bool = False,
               ) -> list[tuple[str, pathlib.Path]]:
    """BFS same-host crawler. Returns ordered list of (canonical_url, cached_path)."""
    if not re.match(r"^https?://", seed):
        raise SystemExit("--crawl needs an http(s) URL")

    cache_dir.mkdir(parents=True, exist_ok=True)
    seed = _canonical_url(seed)
    parsed = urllib.parse.urlparse(seed)
    host = parsed.netloc
    site_root = f"{parsed.scheme}://{host}"
    robots = _load_robots(site_root)

    queue: list[tuple[str, int]] = [(seed, 0)]
    seen: set[str] = {seed}
    out: list[tuple[str, pathlib.Path]] = []

    while queue and len(out) < max_pages:
        url, depth = queue.pop(0)
        if not robots.can_fetch(USER_AGENT, url):
            continue

        slug = _slugify_url(url)
        html_path = cache_dir / f"{slug}.html"
        pdf_path = cache_dir / f"{slug}.pdf"
        cached = html_path if html_path.exists() else (pdf_path if pdf_path.exists() else None)

        if refresh or cached is None:
            try:
                body, ctype = _fetch_one(url)
            except Exception as e:  # noqa: BLE001
                print(f"[discover] skip {url}: {e}"); continue
            if "html" in ctype:
                path = html_path
            elif "pdf" in ctype:
                path = pdf_path
            else:
                continue  # not an HTML or PDF page
            path.write_bytes(body)
            time.sleep(0.5)
        else:
            path = cached

        out.append((url, path))
        if depth >= max_depth:
            continue
        if path.suffix != ".html":
            continue  # only follow links from HTML pages
        html = path.read_text(errors="ignore")
        for link in _extract_links(html, url):
            cu = _canonical_url(link)
            if urllib.parse.urlparse(cu).netloc != host:
                continue
            if cu in seen:
                continue
            seen.add(cu)
            queue.append((cu, depth + 1))

    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 17 passed.

**Note:** The 0.5 s inter-page sleep will slow these tests. That's fine (17 tests × ≤10 pages ≈ under a minute total). If a maintainer later wants to speed up, add a `_SLEEP_BETWEEN_FETCHES = 0.5` module constant and monkey-patch it to 0 in tests. Do NOT add that indirection now — YAGNI.

---

## Task 6: `crawl_site` — robots.txt + cache + refresh

**Files:**
- Modify: `tests/test_discover_crawl.py`

(The core function already handles robots + caching. This task just adds the tests that pin those behaviors.)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_discover_crawl.py`:

```python
def test_crawl_respects_robots_txt(http_server, tmp_path):
    base, routes = http_server
    routes["/robots.txt"] = (b"User-agent: *\nDisallow: /private/\n", "text/plain")
    routes["/seed"] = (b'<a href="/private/x">no</a> <a href="/ok">yes</a>', "text/html")
    routes["/private/x"] = (b"<html>secret</html>", "text/html")
    routes["/ok"] = (b"<html>ok</html>", "text/html")
    pages = discover.crawl_site(f"{base}/seed", max_depth=2, max_pages=99,
                                cache_dir=tmp_path, refresh=True)
    urls = [u for u, _ in pages]
    assert any("/ok" in u for u in urls)
    assert not any("/private/" in u for u in urls)


def test_crawl_uses_cache_on_second_run(http_server, tmp_path, monkeypatch):
    base, routes = http_server
    routes["/seed"] = (b"<html>hi</html>", "text/html")

    # First run: populates cache.
    discover.crawl_site(f"{base}/seed", max_depth=0, max_pages=1,
                        cache_dir=tmp_path, refresh=False)

    # Second run: _fetch_one must not be called.
    calls = []
    real = discover._fetch_one
    def spy(url, timeout=30):
        calls.append(url); return real(url, timeout)
    monkeypatch.setattr(discover, "_fetch_one", spy)

    pages = discover.crawl_site(f"{base}/seed", max_depth=0, max_pages=1,
                                cache_dir=tmp_path, refresh=False)
    assert len(pages) == 1
    assert calls == []


def test_crawl_refresh_bypasses_cache(http_server, tmp_path, monkeypatch):
    base, routes = http_server
    routes["/seed"] = (b"<html>hi</html>", "text/html")

    discover.crawl_site(f"{base}/seed", max_depth=0, max_pages=1,
                        cache_dir=tmp_path, refresh=False)

    calls = []
    real = discover._fetch_one
    def spy(url, timeout=30):
        calls.append(url); return real(url, timeout)
    monkeypatch.setattr(discover, "_fetch_one", spy)

    discover.crawl_site(f"{base}/seed", max_depth=0, max_pages=1,
                        cache_dir=tmp_path, refresh=True)
    assert len(calls) == 1
```

- [ ] **Step 2: Run tests to verify pass (no code changes needed)**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 20 passed. (These tests should pass because Task 5 already implemented robots and cache handling.)

If any of the three fail, the failure identifies a bug in Task 5's `crawl_site` — fix `crawl_site`, then re-run. Do not weaken the tests.

---

## Task 7: `fields_from_pages_llm` (aggregate → chunk → LLM → merge)

**Files:**
- Modify: `src/discover.py`
- Modify: `tests/test_discover_crawl.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_discover_crawl.py`:

```python
def test_fields_from_pages_llm_merges_across_chunks(tmp_path, monkeypatch):
    # Two cached HTML pages with different partial vocabularies.
    p1 = tmp_path / "a.html"; p1.write_text("<html>acdtime: Talk time.</html>")
    p2 = tmp_path / "b.html"; p2.write_text("<html>holdtime: Hold time in seconds.</html>")

    # Force chunking to always yield one chunk per source page.
    monkeypatch.setattr(discover, "_chunk_text", lambda text, size=10_000: text.split("\n\n===\n\n"))

    responses = iter([
        {"acdtime": "Talk."},                              # first chunk
        {"acdtime": "Talk time of ACD calls, in seconds.",  # second chunk: better desc
         "holdtime": "Hold time in seconds."},
    ])
    monkeypatch.setattr(discover, "fields_from_text_llm",
                        lambda text, vendor: next(responses))

    pages = [("https://example.com/a", p1), ("https://example.com/b", p2)]
    merged = discover.fields_from_pages_llm(pages, "Acme")
    assert merged["acdtime"] == "Talk time of ACD calls, in seconds."
    assert merged["holdtime"] == "Hold time in seconds."
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_discover_crawl.py::test_fields_from_pages_llm_merges_across_chunks -v`
Expected: FAIL — `fields_from_pages_llm` not defined.

- [ ] **Step 3: Implement**

Add to `src/discover.py` (after `crawl_site`):

```python
def _page_text(path: pathlib.Path) -> str:
    """Read a cached page (HTML or PDF) and return plain text."""
    if path.suffix == ".pdf":
        try:
            return pdf_text(path)
        except SystemExit:
            return ""  # PDF tools not available; skip this page rather than abort
    return strip_html(path.read_text(errors="ignore"))


def fields_from_pages_llm(pages: list[tuple[str, pathlib.Path]], vendor: str) -> dict:
    """Concatenate cached pages, chunk, run fields_from_text_llm per chunk, merge."""
    text = "\n\n===\n\n".join(_page_text(p) for _, p in pages)
    merged: dict = {}
    for chunk in _chunk_text(text):
        partial = fields_from_text_llm(chunk, vendor)
        merged = _merge_field_maps(merged, partial)
    return merged
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 21 passed.

---

## Task 8: Wire `--crawl` into `main()` + end-to-end test

**Files:**
- Modify: `src/discover.py` (extend `main()`)
- Modify: `tests/test_discover_crawl.py`

- [ ] **Step 1: Write failing end-to-end test**

Append to `tests/test_discover_crawl.py`:

```python
import yaml as _yaml


def test_end_to_end_crawl_writes_catalog_yaml(http_server, tmp_path, monkeypatch):
    base, routes = http_server
    routes["/index"] = (b'<a href="/fields">fields</a>', "text/html")
    routes["/fields"] = (b"<html>acdtime: Talk time of ACD calls.</html>", "text/html")

    # Force engine=auto (no LLM) so this test is hermetic.
    out_path = tmp_path / "acme.yaml"
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(sys, "argv", [
        "discover.py", "Acme",
        "--crawl", f"{base}/index",
        "--max-depth", "2",
        "--max-pages", "5",
        "--engine", "auto",
        "--out", str(out_path),
        "--cache-dir", str(cache_dir),
    ])
    discover.main()

    doc = _yaml.safe_load(out_path.read_text())
    assert doc["meta"]["vendor"] == "Acme"
    assert "acdtime" in doc["fields"]
    # meta.source has one entry per cached page.
    urls = [s.get("url") for s in doc["meta"]["source"] if "url" in s]
    assert any("/fields" in u for u in urls)
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_discover_crawl.py::test_end_to_end_crawl_writes_catalog_yaml -v`
Expected: FAIL — unrecognized `--crawl` / `--cache-dir` argument.

- [ ] **Step 3: Extend `main()`**

Replace the current `main()` body in `src/discover.py` with:

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vendor")
    ap.add_argument("--from-csv", dest="csv", default=None)
    ap.add_argument("--doc", default=None)
    ap.add_argument("--crawl", default=None, help="Seed URL to crawl (http/https).")
    ap.add_argument("--max-depth", type=int, default=2)
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--refresh", action="store_true",
                    help="Ignore cache under fixtures/vendor_docs/<vendor>/.")
    ap.add_argument("--cache-dir", default=None,
                    help="Override cache dir (default: fixtures/vendor_docs/<vendor>/).")
    ap.add_argument("--engine", choices=["auto", "llm"], default="auto")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if not args.csv and not args.doc and not args.crawl:
        sys.exit("give --from-csv <file> and/or --doc <file|url> and/or --crawl <url>")
    if args.max_depth < 0 or args.max_pages < 1:
        sys.exit("--max-depth must be >=0 and --max-pages must be >=1")

    fields: dict = {}
    sources: list = []

    if args.csv:
        fields.update(fields_from_csv(args.csv))
        sources.append({"name": "data export header", "ref": args.csv})

    if args.crawl:
        cache_dir = pathlib.Path(args.cache_dir) if args.cache_dir else \
            ROOT / "fixtures" / "vendor_docs" / args.vendor.lower()
        print(f"[discover] crawling {args.crawl} (host-only, depth<={args.max_depth}, "
              f"pages<={args.max_pages}) -> cache {cache_dir}")
        pages = crawl_site(args.crawl, args.max_depth, args.max_pages, cache_dir, args.refresh)
        if not pages:
            sys.exit(f"[discover] crawl fetched 0 pages; check {cache_dir}")
        if args.engine == "llm":
            crawl_fields = fields_from_pages_llm(pages, args.vendor)
        else:
            text = "\n\n===\n\n".join(_page_text(p) for _, p in pages)
            crawl_fields = fields_from_text_auto(text)
        for k, v in crawl_fields.items():
            if v or k not in fields:
                fields[k] = v or fields.get(k, "")
        for url, p in pages:
            sources.append({"name": p.stem, "url": url})

    if args.doc:
        text = read_source(args.doc)
        doc_fields = fields_from_text_llm(text, args.vendor) if args.engine == "llm" \
            else fields_from_text_auto(text)
        for k, v in doc_fields.items():
            if v or k not in fields:
                fields[k] = v or fields.get(k, "")
        sources.append({"name": "vendor documentation",
                        "url" if re.match(r"^https?://", args.doc) else "ref": args.doc})

    doc = {"meta": {"vendor": args.vendor, "report": "queue", "source": sources},
           "fields": fields}
    out = args.out or str(ROOT / "fixtures" / "vendor_catalogs" / f"{args.vendor.lower()}.yaml")
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    header = ("# DISCOVERED catalog (step 1). Review descriptions before mapping.\n"
              "# Empty descriptions = add them (or re-run with --doc/--engine llm).\n")
    pathlib.Path(out).write_text(header + yaml.safe_dump(doc, sort_keys=False))
    n_desc = sum(1 for v in fields.values() if v)
    print(f"[discover] {len(fields)} fields ({n_desc} with descriptions) -> {out}")
    print(f"           next:  ./add_vendor.sh {args.vendor} {out}")
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_discover_crawl.py -v`
Expected: 22 passed.

Run: `pytest -v`
Expected: full existing suite still passes (no regression in `test_engine_and_automap.py`, `test_contract_queue*.py`, `test_agent_reports.py`).

---

## Task 9: `.gitignore` + README update + smoke run

**Files:**
- Modify (or create): `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Update `.gitignore`**

Check for an existing `.gitignore` in the repo root:

```bash
ls -la .gitignore
```

If it exists, append the following if not already present:

```
# Cached vendor documentation pages produced by `discover.py --crawl`.
fixtures/vendor_docs/
```

If it doesn't exist, create it with just those two lines.

- [ ] **Step 2: Update `README.md`**

Find the discover-usage section in `README.md` (search for `python src/discover.py`) and add one example line after the existing examples:

```
# Crawl a vendor's public documentation site from a seed URL:
python src/discover.py Acme --crawl https://docs.acme.com/wfm/fields --engine llm
```

Keep the example minimal — the CLI `--help` output is the source of truth for flags.

- [ ] **Step 3: Smoke run against a local file server (optional but recommended)**

If `python -m http.server` is available, this is a 60-second sanity check:

```bash
mkdir -p /tmp/lex_smoke && cat > /tmp/lex_smoke/index.html <<'HTML'
<a href="fields.html">fields</a>
HTML
cat > /tmp/lex_smoke/fields.html <<'HTML'
<pre>
acdtime: Talk time of ACD calls, excludes hold time.
holdtime: Time callers spent on hold during ACD calls.
</pre>
HTML
( cd /tmp/lex_smoke && python -m http.server 8123 >/dev/null 2>&1 ) &
SRV=$!
sleep 1
python src/discover.py Smoke --crawl http://127.0.0.1:8123/index.html \
    --max-depth 2 --max-pages 5 --engine auto \
    --cache-dir /tmp/lex_smoke_cache --out /tmp/lex_smoke_catalog.yaml
kill $SRV
cat /tmp/lex_smoke_catalog.yaml
```

Expected: catalog contains `acdtime` and `holdtime` with the descriptions from the seed site; `meta.source` lists both crawled pages.

- [ ] **Step 4: Final full-suite run**

Run: `pytest -v`
Expected: everything passes, including the 22 new tests in `test_discover_crawl.py`.

---

## Definition of Done

- [ ] `pytest -v` is fully green.
- [ ] `python src/discover.py --help` shows `--crawl`, `--max-depth`, `--max-pages`, `--refresh`, `--cache-dir`.
- [ ] End-to-end test writes a well-formed catalog YAML with `meta.source` populated per cached page.
- [ ] Existing catalog contract tests (`test_contract_queue*.py`) remain green.
- [ ] No changes outside `src/discover.py`, `tests/test_discover_crawl.py`, `README.md`, `.gitignore`.

---

## Self-review notes

- Spec coverage: every function listed in the spec's function table maps to a task (T1: URL helpers; T2: `_fetch_one`/`_extract_links`; T3: `_chunk_text`; T4: `_load_robots`; T5-6: `crawl_site`; T7: `fields_from_pages_llm`; T8: CLI). All 9 tests named in the spec's testing table are present (renamed slightly for consistency; behavior identical). The `.gitignore` and README items are in T9.
- Type consistency: `crawl_site` returns `list[tuple[str, pathlib.Path]]` — stable across T5 (defined), T6 (spy tests unpack the tuples), T7 (`fields_from_pages_llm` consumes the same shape), T8 (main iterates `for url, p in pages`). `_fetch_one` signature `(url, timeout=30) -> (bytes, str)` is stable across T2 (defined), T6 (monkey-patched spy uses same signature).
- No placeholders: every code step ships complete code; every test step ships complete assertions.
- Deviation from spec: added `--cache-dir` CLI flag (not in the spec) so the end-to-end test can point cache at `tmp_path`. Default behavior is unchanged (uses `fixtures/vendor_docs/<vendor>/`). Small, useful, low-risk addition — flagged here for reviewer awareness.
