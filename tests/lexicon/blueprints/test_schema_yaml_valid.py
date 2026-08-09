from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "ontology" / "blueprints" / "schema.yaml"


def test_schema_yaml_parses():
    raw = yaml.safe_load(SCHEMA.read_text())
    assert isinstance(raw, dict)


def test_schema_yaml_has_all_top_level_keys():
    raw = yaml.safe_load(SCHEMA.read_text())
    required = {
        "platforms", "routing_models", "channels",
        "required_sections", "concept_vocabulary",
        "object_footprint_columns", "event_subsection_fields",
    }
    missing = required - raw.keys()
    assert not missing, f"schema.yaml is missing keys: {sorted(missing)}"


def test_schema_yaml_has_expected_closed_enums():
    raw = yaml.safe_load(SCHEMA.read_text())
    assert "salesforce" in raw["platforms"]
    assert "queue_based" in raw["routing_models"]
    assert "voice" in raw["channels"]


def test_schema_yaml_has_all_required_sections():
    raw = yaml.safe_load(SCHEMA.read_text())
    expected = {"Overview", "Prerequisites", "Configuration steps",
                "Object footprint", "ACD event mapping", "Validation"}
    assert expected <= set(raw["required_sections"])
