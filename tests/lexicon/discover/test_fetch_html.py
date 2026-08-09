from pathlib import Path
import pytest

from lexicon.discover.cache import DiskCache
from lexicon.discover.fetch.html import fetch_html_source
from lexicon.discover.models import RegistrySource


def test_uses_cached_body(tmp_path):
    cache = DiskCache(tmp_path)
    url = "https://example.com/docs"
    cache.put("http", url, b"<html><title>hi</title><body><p>abc</p></body></html>")

    src = RegistrySource(kind="html_doc", role="primary", url=url,
                         crawl={"max_depth": 0, "max_pages": 1})

    def boom(u):
        raise AssertionError(f"should not have fetched {u}")

    docs = fetch_html_source(src, cache=cache, _fetcher=boom)
    assert len(docs) == 1
    assert docs[0].kind == "html"
    assert docs[0].url == url
    assert "abc" in docs[0].text
    assert docs[0].title == "hi"


def test_fetches_when_missing_and_caches(tmp_path):
    cache = DiskCache(tmp_path)
    url = "https://example.com/docs"

    def fake_fetcher(u):
        assert u == url
        return b"<html><body><h1>live</h1></body></html>"

    src = RegistrySource(kind="html_doc", role="primary", url=url,
                         crawl={"max_depth": 0, "max_pages": 1})
    docs = fetch_html_source(src, cache=cache, _fetcher=fake_fetcher)
    assert "live" in docs[0].text
    # second call should be served from cache
    docs2 = fetch_html_source(
        src, cache=cache, _fetcher=lambda u: pytest.fail("must not refetch"),
    )
    assert docs2[0].text == docs[0].text


def test_offline_cache_miss_raises(tmp_path):
    src = RegistrySource(kind="html_doc", role="primary",
                         url="https://example.com/missing",
                         crawl={"max_depth": 0, "max_pages": 1})
    cache = DiskCache(tmp_path, offline=True)
    with pytest.raises(RuntimeError):
        fetch_html_source(src, cache=cache, _fetcher=None)
