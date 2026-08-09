"""Content-addressed on-disk cache. Used for HTTP fetches AND LLM responses.

Layout: <root>/<namespace>/<sha256>.bin
Namespaces used by the pipeline: "http", "llm", "resolver".

`offline=True` disables writes (used in CI to guarantee cache is authoritative).
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path


class DiskCache:
    def __init__(self, root: Path, offline: bool = False):
        self.root = Path(root)
        self.offline = offline
        self.root.mkdir(parents=True, exist_ok=True)

    def _key_path(self, namespace: str, key: str) -> Path:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / namespace / f"{h}.bin"

    def get(self, namespace: str, key: str) -> bytes | None:
        p = self._key_path(namespace, key)
        return p.read_bytes() if p.exists() else None

    def put(self, namespace: str, key: str, value: bytes) -> None:
        # NOTE: not thread-safe. Two concurrent writers to the same key race on
        # the rename; last-writer-wins. Fine for v1 (single-threaded pipeline).
        if self.offline:
            raise RuntimeError(
                f"offline cache: refusing to write namespace={namespace} key={key!r}"
            )
        p = self._key_path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(value)
        tmp.replace(p)   # atomic on POSIX; also atomic on Windows in Python 3.3+

    def get_json(self, namespace: str, key: str):
        b = self.get(namespace, key)
        return None if b is None else json.loads(b.decode("utf-8"))

    def put_json(self, namespace: str, key: str, value) -> None:
        self.put(namespace, key, json.dumps(value, sort_keys=True).encode("utf-8"))
