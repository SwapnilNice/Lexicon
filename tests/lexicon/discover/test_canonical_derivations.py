from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_handle_time_queue_has_derivation():
    canon = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())
    ht = canon["queue"]["HandleTime"]
    assert "derivation" in ht
    d = ht["derivation"]
    assert d["formula"] == "{talk} + {hold}"
    tags = [c["tag"] for c in d["components"]]
    assert "talk_time_like" in tags and "hold_time_like" in tags
    assert "acw_time_like" in d.get("forbid_tags", [])


def test_handle_time_agent_queue_has_derivation():
    canon = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())
    ht = canon["agent_queue"]["HandleTime"]
    assert "derivation" in ht


def test_no_existing_field_definition_changed():
    """Sanity: HandleTime.definition and HandleTime.unit stay exactly as before."""
    canon = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())
    ht = canon["queue"]["HandleTime"]
    assert ht["unit"] == "duration_seconds"
    assert "TALK TIME + HOLD TIME" in ht["definition"]
    assert "After-Call-Work" in ht["definition"]
