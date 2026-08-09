"""OpenAPI schema extractor. Emits RawField per property.

Surfaces the description text plus any `x-unit` / `format` hints, so the
enricher's unit-inference step has strong structural signals to key off.
"""
from __future__ import annotations
import json

from ..models import FieldSource, RawField, SourceDoc


def _describe(prop: dict) -> str:
    parts = []
    if prop.get("description"):
        parts.append(prop["description"])
    if "format" in prop:
        parts.append(f"(format: {prop['format']})")
    if "x-unit" in prop:
        parts.append(f"(unit: {prop['x-unit']})")
    if "type" in prop:
        parts.append(f"(type: {prop['type']})")
    return " ".join(parts).strip()


def extract_openapi(doc: SourceDoc) -> list[RawField]:
    if doc.kind != "openapi_schema":
        return []
    schema = json.loads(doc.content)
    props = schema.get("properties", {}) or {}
    out: list[RawField] = []
    for name, prop in props.items():
        desc = _describe(prop)
        out.append(RawField(
            name=name,
            description=desc,
            source=FieldSource(
                doc_id=doc.id, url=doc.url,
                locator=f"/properties/{name}",
                snippet=f"{name} — {desc[:120]}",
            ),
            extractor="openapi",
            confidence_extraction=0.98,
        ))
    return out
