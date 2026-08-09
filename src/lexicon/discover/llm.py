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
            text = cached.get("text")
            if text is None:
                raise RuntimeError(f"LLM cache entry malformed (missing 'text' field): key={key!r}")
            return text
        if self.offline:
            raise RuntimeError(f"LLM cache miss in offline mode: model={model} prompt[:40]={prompt[:40]!r}")
        text = self._call_impl(model, prompt)
        self.cache.put_json("llm", key, {"text": text})
        return text

    @staticmethod
    def _real_call(model: str, prompt: str) -> str:
        """Real LLM call. Two auth paths, tried in order:

        1. **Anthropic API key** (env var `ANTHROPIC_API_KEY`) — direct API call
           via the `anthropic` SDK. Metered against your API billing.
        2. **Claude Code CLI** (`claude` on PATH) — subprocess call via
           `claude -p ...` using stdin. Reuses your Claude Code OAuth
           credentials, so no API key is needed. Metered against your Claude
           subscription. This is the fallback for developers who already
           use Claude Code interactively.

        If neither is available, a RuntimeError explains both options.
        """
        import os
        # --- Path A: ANTHROPIC_API_KEY + anthropic SDK ---
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic  # type: ignore
            except ImportError:
                pass  # fall through to CLI path
            else:
                client = anthropic.Anthropic()
                msg = client.messages.create(
                    model=model,
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text_blocks = [b for b in msg.content if getattr(b, "type", None) == "text"]
                if not text_blocks:
                    raise RuntimeError(
                        f"LLM returned no text block (model={model}, "
                        f"stop_reason={getattr(msg, 'stop_reason', None)!r})"
                    )
                return text_blocks[0].text

        # --- Path B: Claude Code CLI subprocess ---
        import shutil
        cli = shutil.which("claude")
        if cli is None:
            raise RuntimeError(
                "No LLM auth available. Either:\n"
                "  (a) Set ANTHROPIC_API_KEY (get one from https://console.anthropic.com), or\n"
                "  (b) Install Claude Code (`npm install -g @anthropic-ai/claude-code`) "
                "and run `claude` once to authenticate. Then the discovery pipeline "
                "will use your Claude Code credentials automatically."
            )
        import subprocess
        try:
            result = subprocess.run(
                [cli, "-p", "--output-format", "text", "--model", model],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude CLI timed out after 180s (model={model})") from e
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI failed (exit {result.returncode}): "
                f"{(result.stderr or result.stdout).strip()[:500]}"
            )
        return result.stdout.strip()
