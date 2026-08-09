import json
import pytest

from lexicon.discover.cache import DiskCache
from lexicon.discover.fetch.openapi import fetch_openapi_source
from lexicon.discover.models import RegistrySource


SPEC = {
    "openapi": "3.0.0",
    "components": {
        "schemas": {
            "QueueMetrics": {
                "type": "object",
                "description": "Aggregate queue metrics.",
                "properties": {
                    "nHandled": {"type": "integer", "description": "Count handled."},
                    "tTalk": {"type": "integer", "description": "Talk time in ms."},
                },
            },
            "AgentState": {
                "type": "object",
                "description": "Agent presence state.",
                "properties": {
                    "readyTime": {"type": "integer", "description": "Time ready, seconds."},
                },
            },
        }
    },
}


def test_emits_one_doc_per_schema(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put("http", "https://x/openapi.json", json.dumps(SPEC).encode())
    src = RegistrySource(kind="openapi", role="primary",
                         url="https://x/openapi.json")
    docs = fetch_openapi_source(src, cache=cache, _fetcher=lambda u: pytest.fail("cached"))
    assert {d.title for d in docs} == {"QueueMetrics", "AgentState"}
    for d in docs:
        assert d.kind == "openapi_schema"


def test_schema_content_contains_properties(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put("http", "https://x/openapi.json", json.dumps(SPEC).encode())
    src = RegistrySource(kind="openapi", role="primary",
                         url="https://x/openapi.json")
    docs = fetch_openapi_source(src, cache=cache)
    qm = next(d for d in docs if d.title == "QueueMetrics")
    body = json.loads(qm.content)
    assert "properties" in body
    assert "nHandled" in body["properties"]


def test_missing_url_returns_empty(tmp_path):
    src = RegistrySource(kind="openapi", role="primary", url=None)
    assert fetch_openapi_source(src, cache=DiskCache(tmp_path)) == []


def test_circular_refs_do_not_crash(tmp_path):
    circular = {
        "openapi": "3.0.0",
        "components": {"schemas": {
            "A": {"type": "object", "properties": {"b": {"$ref": "#/components/schemas/B"}}},
            "B": {"type": "object", "properties": {"a": {"$ref": "#/components/schemas/A"}}},
        }},
    }
    cache = DiskCache(tmp_path)
    cache.put("http", "https://x/openapi.json", json.dumps(circular).encode())
    src = RegistrySource(kind="openapi", role="primary", url="https://x/openapi.json")
    # Should not raise RecursionError
    docs = fetch_openapi_source(src, cache=cache)
    assert len(docs) == 2  # A and B both emitted


def test_bad_ref_does_not_crash(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "components": {"schemas": {
            "X": {"type": "object", "properties": {"y": {"$ref": "#/components/schemas/Missing"}}},
        }},
    }
    cache = DiskCache(tmp_path)
    cache.put("http", "https://x/openapi.json", json.dumps(spec).encode())
    src = RegistrySource(kind="openapi", role="primary", url="https://x/openapi.json")
    docs = fetch_openapi_source(src, cache=cache)  # should not raise
    assert len(docs) == 1
