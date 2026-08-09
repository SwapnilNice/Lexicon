import json

from lexicon.discover.extract.openapi import extract_openapi
from lexicon.discover.models import SourceDoc


def _schema_doc(name, schema):
    return SourceDoc(
        id="s1", kind="openapi_schema",
        url=f"https://x#/components/schemas/{name}",
        title=name,
        content=json.dumps(schema),
        text="",
    )


def test_emits_one_field_per_property():
    schema = {
        "type": "object",
        "properties": {
            "nHandled": {"type": "integer", "description": "Count of handled contacts."},
            "tTalk": {"type": "integer", "description": "Talk time in ms.", "x-unit": "milliseconds"},
        },
    }
    raws = extract_openapi(_schema_doc("QueueMetrics", schema))
    assert {r.name for r in raws} == {"nHandled", "tTalk"}
    tt = next(r for r in raws if r.name == "tTalk")
    assert "milliseconds" in tt.description  # x-unit surfaced
    assert tt.extractor == "openapi"
    assert tt.confidence_extraction >= 0.95


def test_no_properties_returns_empty():
    doc = _schema_doc("Empty", {"type": "object"})
    assert extract_openapi(doc) == []


def test_provenance_uses_json_pointer_locator():
    schema = {"type": "object", "properties": {"x": {"type": "integer", "description": "x"}}}
    raws = extract_openapi(_schema_doc("S", schema))
    assert raws[0].source.locator == "/properties/x"
