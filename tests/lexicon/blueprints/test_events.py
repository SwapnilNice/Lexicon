from pathlib import Path
import textwrap
import pytest

from lexicon.blueprints.events import load_events, validate_taxonomy, EventsError


def _write(path: Path, body: str):
    path.write_text(textwrap.dedent(body))


def test_load_valid_events(tmp_path):
    _write(tmp_path / "events.yaml", """
        meta: { version: "1.0", description: "d" }
        presence_states:
          ready: { description: "d" }
          offline: { description: "d" }
        events:
          interaction.received:
            description: "d"
            prerequisites: []
            optional: false
          interaction.routed:
            description: "d"
            prerequisites: [interaction.received]
            optional: false
    """)
    t = load_events(tmp_path / "events.yaml")
    assert "interaction.received" in t.events
    assert t.events["interaction.routed"].prerequisites == ("interaction.received",)
    assert not t.events["interaction.received"].optional
    assert "ready" in t.presence_states


def test_missing_meta_raises(tmp_path):
    _write(tmp_path / "events.yaml", """
        presence_states: { ready: { description: "d" } }
        events: { }
    """)
    with pytest.raises(EventsError, match="meta"):
        load_events(tmp_path / "events.yaml")


def test_cycle_detected(tmp_path):
    _write(tmp_path / "events.yaml", """
        meta: { version: "1.0", description: "d" }
        presence_states:
          ready: { description: "d" }
        events:
          a:
            description: "d"
            prerequisites: [b]
            optional: false
          b:
            description: "d"
            prerequisites: [a]
            optional: false
    """)
    t = load_events(tmp_path / "events.yaml")
    errs = validate_taxonomy(t)
    assert any("cycle" in e.lower() for e in errs), errs


def test_orphan_prerequisite_detected(tmp_path):
    _write(tmp_path / "events.yaml", """
        meta: { version: "1.0", description: "d" }
        presence_states:
          ready: { description: "d" }
        events:
          x:
            description: "d"
            prerequisites: [nonexistent]
            optional: false
    """)
    t = load_events(tmp_path / "events.yaml")
    errs = validate_taxonomy(t)
    assert any("nonexistent" in e for e in errs), errs


def test_attribute_reference_target_missing_detected(tmp_path):
    _write(tmp_path / "events.yaml", """
        meta: { version: "1.0", description: "d" }
        presence_states:
          ready: { description: "d" }
        events:
          agent.presence.change:
            description: "d"
            prerequisites: []
            optional: false
            attributes:
              from_state:
                references: nonexistent_taxonomy
    """)
    t = load_events(tmp_path / "events.yaml")
    errs = validate_taxonomy(t)
    assert any("nonexistent_taxonomy" in e for e in errs), errs


def test_load_the_real_events():
    """Sanity — committed events.yaml loads and validates cleanly."""
    root = Path(__file__).resolve().parents[3]
    t = load_events(root / "ontology" / "blueprints" / "events.yaml")
    errs = validate_taxonomy(t)
    assert errs == [], f"real events.yaml has errors: {errs}"
