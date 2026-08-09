from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
EVENTS = ROOT / "ontology" / "blueprints" / "events.yaml"


def test_events_yaml_parses():
    raw = yaml.safe_load(EVENTS.read_text())
    assert isinstance(raw, dict)


def test_events_yaml_has_meta_and_presence_states_and_events():
    raw = yaml.safe_load(EVENTS.read_text())
    for key in ("meta", "presence_states", "events"):
        assert key in raw, f"events.yaml missing top-level key {key!r}"


def test_all_required_events_are_present():
    raw = yaml.safe_load(EVENTS.read_text())
    required = {
        "interaction.received", "interaction.routed", "interaction.accepted",
        "interaction.talk.start", "interaction.talk.end",
        "interaction.acw.start", "interaction.acw.end",
        "interaction.abandoned", "interaction.completed",
        "agent.login", "agent.logout", "agent.presence.change",
    }
    missing = required - set(raw["events"].keys())
    assert not missing, f"events.yaml is missing required events: {sorted(missing)}"


def test_presence_states_taxonomy_complete():
    raw = yaml.safe_load(EVENTS.read_text())
    required = {"ready", "not_ready", "busy", "acw", "offline"}
    missing = required - set(raw["presence_states"].keys())
    assert not missing, f"presence_states missing: {sorted(missing)}"


def test_projects_to_canonical_wfm_hooks_present():
    """Sub-project B4 will consume these hints. Test they're wired up now."""
    raw = yaml.safe_load(EVENTS.read_text())
    assert raw["events"]["interaction.talk.start"].get("projects_to_canonical_wfm") == "talk_time"
    assert raw["events"]["interaction.hold.start"].get("projects_to_canonical_wfm") == "hold_time"
    assert raw["events"]["interaction.acw.start"].get("projects_to_canonical_wfm") == "acw_time"
