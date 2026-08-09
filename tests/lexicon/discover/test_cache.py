import json
from pathlib import Path
import pytest

from lexicon.discover.cache import DiskCache


def test_put_get_roundtrip(tmp_path):
    c = DiskCache(tmp_path)
    c.put("ns", "k1", b"payload")
    assert c.get("ns", "k1") == b"payload"


def test_missing_returns_none(tmp_path):
    c = DiskCache(tmp_path)
    assert c.get("ns", "missing") is None


def test_namespaces_are_isolated(tmp_path):
    c = DiskCache(tmp_path)
    c.put("html", "k", b"a")
    c.put("llm", "k", b"b")
    assert c.get("html", "k") == b"a"
    assert c.get("llm", "k") == b"b"


def test_put_get_json(tmp_path):
    c = DiskCache(tmp_path)
    c.put_json("llm", "prompt-1", {"answer": "hi"})
    assert c.get_json("llm", "prompt-1") == {"answer": "hi"}


def test_key_hashing_is_stable(tmp_path):
    c = DiskCache(tmp_path)
    p1 = c._key_path("ns", "hello world")
    p2 = c._key_path("ns", "hello world")
    assert p1 == p2


def test_offline_mode_disallows_writes(tmp_path):
    c = DiskCache(tmp_path, offline=True)
    with pytest.raises(RuntimeError, match="offline"):
        c.put("ns", "k", b"x")


def test_offline_mode_allows_reads(tmp_path):
    c = DiskCache(tmp_path)
    c.put("ns", "k", b"x")
    c2 = DiskCache(tmp_path, offline=True)
    assert c2.get("ns", "k") == b"x"
