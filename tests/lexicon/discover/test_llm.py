from pathlib import Path
import pytest

from lexicon.discover.cache import DiskCache
from lexicon.discover.llm import LLMClient


def test_returns_cached_response(tmp_path):
    cache = DiskCache(tmp_path)
    # pre-seed the cache with what "the LLM" would have returned
    cache.put_json("llm", "claude-haiku-4-5-20251001||what is 2+2?", {"text": "4"})
    client = LLMClient(cache=cache, offline=True)      # offline: must not call network
    resp = client.complete(model="claude-haiku-4-5-20251001", prompt="what is 2+2?")
    assert resp == "4"


def test_offline_raises_on_cache_miss(tmp_path):
    client = LLMClient(cache=DiskCache(tmp_path), offline=True)
    with pytest.raises(RuntimeError, match="cache miss"):
        client.complete(model="claude-haiku-4-5-20251001", prompt="unseen prompt")


def test_cache_key_is_model_plus_prompt(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put_json("llm", "claude-sonnet-4-6||q", {"text": "sonnet"})
    cache.put_json("llm", "claude-haiku-4-5-20251001||q", {"text": "haiku"})
    client = LLMClient(cache=cache, offline=True)
    assert client.complete(model="claude-sonnet-4-6", prompt="q") == "sonnet"
    assert client.complete(model="claude-haiku-4-5-20251001", prompt="q") == "haiku"


def test_live_call_caches_result(tmp_path, monkeypatch):
    cache = DiskCache(tmp_path)
    calls = []

    def fake_call(model, prompt):
        calls.append((model, prompt))
        return "live-answer"

    client = LLMClient(cache=cache, offline=False, _call_impl=fake_call)
    r1 = client.complete(model="claude-haiku-4-5-20251001", prompt="q")
    r2 = client.complete(model="claude-haiku-4-5-20251001", prompt="q")
    assert r1 == "live-answer" and r2 == "live-answer"
    assert len(calls) == 1     # second call served from cache
