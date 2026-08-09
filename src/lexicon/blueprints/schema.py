"""Loader for ontology/blueprints/schema.yaml. Returns SchemaDef or raises SchemaError."""
from __future__ import annotations
from pathlib import Path
import yaml

from .models import SchemaDef


REQUIRED_KEYS = {
    "platforms", "routing_models", "channels",
    "required_sections", "concept_vocabulary",
    "object_footprint_columns", "event_subsection_fields",
}


class SchemaError(ValueError):
    pass


def load_schema(path: Path) -> SchemaDef:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    missing = REQUIRED_KEYS - raw.keys()
    if missing:
        raise SchemaError(f"schema.yaml missing keys: {sorted(missing)}")
    for k in ("platforms", "routing_models", "channels", "concept_vocabulary"):
        if not raw[k]:
            raise SchemaError(f"schema.yaml: {k!r} must be non-empty")
    if not raw["required_sections"]:
        raise SchemaError("schema.yaml: required_sections must be non-empty")
    return SchemaDef(
        platforms=set(raw["platforms"]),
        routing_models=set(raw["routing_models"]),
        channels=set(raw["channels"]),
        required_sections=list(raw["required_sections"]),
        concept_vocabulary=set(raw["concept_vocabulary"]),
        object_footprint_columns=list(raw["object_footprint_columns"]),
        event_subsection_fields=set(raw["event_subsection_fields"]),
    )
