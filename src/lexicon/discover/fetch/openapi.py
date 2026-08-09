"""OpenAPI source fetcher. Emits one SourceDoc per named schema under
components.schemas — with $ref resolution done in place (best-effort).

Non-goals for v1: full OpenAPI validation, external $ref resolution
(only same-document $refs are inlined), OpenAPI 2.0 (Swagger) support.
"""
from __future__ import annotations
import copy
import json
import hashlib
from typing import Callable

import yaml

from ..cache import DiskCache
from ..models import RegistrySource, SourceDoc


def _default_fetcher(url: str) -> bytes:
    import httpx
    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": "Lexicon-discover/1.0"})
    r.raise_for_status()
    return r.content


def _resolve_refs(node, root, _depth=0, _visiting=None):
    if _visiting is None:
        _visiting = set()
    if isinstance(node, dict):
        ref_value = node.get("$ref")
        if isinstance(ref_value, str) and ref_value.startswith("#/"):
            ref = ref_value
            if ref in _visiting or _depth > 20:
                return {}  # break cycle; caller sees empty schema
            parts = ref[2:].split("/")
            target = root
            try:
                for p in parts:
                    target = target[p]
            except (KeyError, TypeError):
                return {}  # bad ref — emit empty rather than crash
            return _resolve_refs(copy.deepcopy(target), root, _depth + 1, _visiting | {ref})
        return {k: _resolve_refs(v, root, _depth, _visiting) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(x, root, _depth, _visiting) for x in node]
    return node


def fetch_openapi_source(
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
            raise RuntimeError(f"OpenAPI cache miss in offline mode: {source.url}")
        body = fetcher(source.url)
        cache.put("http", source.url, body)
    text = body.decode("utf-8", errors="ignore")
    spec = yaml.safe_load(text) if source.url.endswith((".yaml", ".yml")) else json.loads(text)

    # OpenAPI 3.x stores schemas under `components.schemas`; Swagger 2.0
    # stores them under `definitions`. Check both.
    schemas_30 = (spec.get("components", {}) or {}).get("schemas", {}) or {}
    schemas_20 = spec.get("definitions", {}) or {}
    if schemas_30:
        schemas = schemas_30
        pointer_prefix = "#/components/schemas"
    elif schemas_20:
        schemas = schemas_20
        pointer_prefix = "#/definitions"
    else:
        schemas = {}
        pointer_prefix = "#/schemas"

    docs = []
    for name, schema in schemas.items():
        resolved = _resolve_refs(schema, spec)
        doc_id = f"openapi:{hashlib.sha256((source.url + '#' + name).encode()).hexdigest()[:12]}"
        docs.append(SourceDoc(
            id=doc_id, kind="openapi_schema",
            url=source.url + f"{pointer_prefix}/{name}",
            title=name,
            content=json.dumps(resolved),
            text="",
        ))
    return docs
