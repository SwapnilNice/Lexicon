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


def test_load_robots_returns_parser_that_disallows_declared_paths(http_server):
    base, routes = http_server
    routes["/robots.txt"] = (b"User-agent: *\nDisallow: /private/\n", "text/plain")
    rp = discover._load_robots(base)
    assert rp.can_fetch(discover.USER_AGENT, f"{base}/public") is True
    assert rp.can_fetch(discover.USER_AGENT, f"{base}/private/x") is False


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
