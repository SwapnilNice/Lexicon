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


def test_malformed_cache_entry_raises(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put_json("llm", "claude-haiku-4-5-20251001||q", {"result": "bad"})  # missing 'text'
    client = LLMClient(cache=cache, offline=True)
    with pytest.raises(RuntimeError, match="malformed"):
        client.complete(model="claude-haiku-4-5-20251001", prompt="q")


def test_real_call_error_when_no_auth_and_no_cli(tmp_path, monkeypatch):
    """With no ANTHROPIC_API_KEY AND no claude CLI on PATH, the error names
    BOTH auth options so a first-time user knows what to do."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)   # no claude CLI

    with pytest.raises(RuntimeError) as ei:
        LLMClient._real_call("claude-haiku-4-5-20251001", "hi")
    msg = str(ei.value)
    assert "ANTHROPIC_API_KEY" in msg
    assert "claude" in msg.lower() and "code" in msg.lower()


def test_real_call_uses_claude_cli_when_no_api_key(tmp_path, monkeypatch):
    """With no ANTHROPIC_API_KEY but claude CLI present, `_real_call` shells
    out to `claude -p` and returns its stdout."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/fake/bin/claude" if name == "claude" else None)

    invocations = []

    class FakeResult:
        returncode = 0
        stdout = "cli-answer\n"
        stderr = ""

    def fake_run(cmd, input, capture_output, text, timeout):
        invocations.append({"cmd": cmd, "input": input})
        return FakeResult()

    monkeypatch.setattr("subprocess.run", fake_run)

    result = LLMClient._real_call("claude-sonnet-4-6", "what is 2+2?")
    assert result == "cli-answer"
    assert invocations[0]["cmd"][0] == "/fake/bin/claude"
    assert "-p" in invocations[0]["cmd"]
    assert "claude-sonnet-4-6" in invocations[0]["cmd"]
    assert invocations[0]["input"] == "what is 2+2?"


def test_real_call_cli_nonzero_exit_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/fake/bin/claude" if name == "claude" else None)

    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "authentication failed"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: FakeResult())

    with pytest.raises(RuntimeError, match="claude CLI failed.*authentication failed"):
        LLMClient._real_call("claude-haiku-4-5-20251001", "hi")
