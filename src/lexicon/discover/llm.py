"""LLM client with (model, prompt)-keyed disk caching.

Every call is cached. Re-runs on the same inputs never hit the network.
Offline mode raises RuntimeError on cache miss — used in CI to guarantee
the committed cache is authoritative.
"""
from __future__ import annotations
from typing import Callable

from .cache import DiskCache


class LLMClient:
    def __init__(
        self,
        cache: DiskCache,
        offline: bool = False,
        _call_impl: Callable[[str, str], str] | None = None,
    ):
        self.cache = cache
        self.offline = offline
        self._call_impl = _call_impl or self._real_call

    def complete(self, *, model: str, prompt: str) -> str:
        key = f"{model}||{prompt}"
        cached = self.cache.get_json("llm", key)
        if cached is not None:
            return cached["text"]
        if self.offline:
            raise RuntimeError(f"LLM cache miss in offline mode: model={model} prompt[:40]={prompt[:40]!r}")
        text = self._call_impl(model, prompt)
        self.cache.put_json("llm", key, {"text": text})
        return text

    @staticmethod
    def _real_call(model: str, prompt: str) -> str:
        """Real API call. Only imports anthropic when actually invoked."""
        import os
        import anthropic  # type: ignore
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
