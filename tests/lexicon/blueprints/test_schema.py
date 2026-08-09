from pathlib import Path
import textwrap
import pytest

from lexicon.blueprints.schema import load_schema, SchemaError


def _write(path: Path, body: str):
    path.write_text(textwrap.dedent(body))


def test_load_valid_schema(tmp_path):
    _write(tmp_path / "schema.yaml", """
        platforms: [salesforce, dynamics365]
        routing_models: [queue_based]
        channels: [voice]
        required_sections:
          - "Overview"
          - "Prerequisites"
        concept_vocabulary: [routing_entity]
        object_footprint_columns:
          - "Concept"
          - "Platform object.field"
        event_subsection_fields:
          - "Recorded in"
          - "Trigger"
    """)
    s = load_schema(tmp_path / "schema.yaml")
    assert s.platforms == {"salesforce", "dynamics365"}
    assert s.routing_models == {"queue_based"}
    assert s.channels == {"voice"}
    assert s.required_sections == ["Overview", "Prerequisites"]
    assert s.concept_vocabulary == {"routing_entity"}


def test_missing_top_level_key_raises(tmp_path):
    _write(tmp_path / "schema.yaml", """
        platforms: [salesforce]
        routing_models: [queue_based]
        # missing channels + others
    """)
    with pytest.raises(SchemaError, match="channels"):
        load_schema(tmp_path / "schema.yaml")


def test_empty_platform_list_raises(tmp_path):
    _write(tmp_path / "schema.yaml", """
        platforms: []
        routing_models: [queue_based]
        channels: [voice]
        required_sections: [Overview]
        concept_vocabulary: [routing_entity]
        object_footprint_columns: [Concept]
        event_subsection_fields: [Recorded in]
    """)
    with pytest.raises(SchemaError, match="platforms.*empty"):
        load_schema(tmp_path / "schema.yaml")


def test_load_the_real_schema():
    """Sanity — the committed schema.yaml loads without error."""
    root = Path(__file__).resolve().parents[3]
    s = load_schema(root / "ontology" / "blueprints" / "schema.yaml")
    assert "salesforce" in s.platforms
    assert "Overview" in s.required_sections
