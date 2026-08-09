from pathlib import Path
import textwrap

import pytest

from lexicon.blueprints.events import load_events
from lexicon.blueprints.parser import parse_blueprint
from lexicon.blueprints.schema import load_schema
from lexicon.blueprints.validator import validate

ROOT = Path(__file__).resolve().parents[3]


def _write(tmp_path, name, body):
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    p = tmp_path / name
    p.write_text(textwrap.dedent(body).lstrip("\n"))
    return p


def _load_real_schema_events():
    return (
        load_schema(ROOT / "ontology" / "blueprints" / "schema.yaml"),
        load_events(ROOT / "ontology" / "blueprints" / "events.yaml"),
    )


VALID_MIN = """
---
platform: salesforce
platform_display_name: "Salesforce"
routing_model: queue_based
channels: [voice]
version: "1.0"
last_verified: 2026-08-09
platform_version_verified_against: "Spring '26"
authored_by: "T"
produces_events: [interaction.received, interaction.routed, interaction.accepted,
                  interaction.talk.start, interaction.talk.end,
                  interaction.acw.start, interaction.acw.end,
                  interaction.abandoned, interaction.completed,
                  agent.login, agent.logout, agent.presence.change]
---
# Overview
x
# Prerequisites
x
# Configuration steps
x
# Object footprint
| Concept | Platform object.field | Populated when | Notes |
|---|---|---|---|
| routing_entity | Queue.Name | admin creates | n |
# ACD event mapping

### interaction.received
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** none

### interaction.routed
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.received

### interaction.accepted
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.routed

### interaction.talk.start
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.accepted

### interaction.talk.end
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.talk.start

### interaction.acw.start
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.talk.end

### interaction.acw.end
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.acw.start

### interaction.abandoned
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.received

### interaction.completed
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** interaction.acw.end

### agent.login
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** none

### agent.logout
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** agent.login

### agent.presence.change
- **Recorded in:** X
- **Trigger:** Y
- **Prerequisite events:** agent.login
# Validation
x
"""


def test_valid_blueprint_no_errors(tmp_path):
    schema, events = _load_real_schema_events()
    p = _write(tmp_path, "salesforce/queue_based.md", VALID_MIN)
    bp = parse_blueprint(p)
    errors = validate(bp, schema, events)
    # Freshness warning allowed; no errors.
    errs = [e for e in errors if e.severity == "error"]
    assert errs == [], f"unexpected errors: {errs}"


def test_missing_platform_frontmatter_key_is_error(tmp_path):
    schema, events = _load_real_schema_events()
    body = VALID_MIN.replace("platform: salesforce\n", "")
    p = _write(tmp_path, "salesforce/queue_based.md", body)
    bp = parse_blueprint(p)
    errors = validate(bp, schema, events)
    assert any(e.severity == "error" and "platform" in e.message.lower() for e in errors)


def test_unknown_platform_is_error(tmp_path):
    schema, events = _load_real_schema_events()
    body = VALID_MIN.replace("platform: salesforce", "platform: fake_crm")
    p = _write(tmp_path, "fake_crm/queue_based.md", body)
    bp = parse_blueprint(p)
    errors = validate(bp, schema, events)
    assert any(e.severity == "error" and "fake_crm" in e.message for e in errors)


def test_file_path_does_not_match_frontmatter_is_error(tmp_path):
    schema, events = _load_real_schema_events()
    p = _write(tmp_path, "dynamics365/queue_based.md", VALID_MIN)  # frontmatter says salesforce
    bp = parse_blueprint(p)
    errors = validate(bp, schema, events)
    assert any(e.severity == "error" and "path" in e.message.lower() for e in errors)


def test_produces_events_unknown_event_is_error(tmp_path):
    schema, events = _load_real_schema_events()
    body = VALID_MIN.replace("agent.presence.change", "made.up.event")
    p = _write(tmp_path, "salesforce/queue_based.md", body)
    bp = parse_blueprint(p)
    errors = validate(bp, schema, events)
    assert any(e.severity == "error" and "made.up.event" in e.message for e in errors)


def test_channels_as_scalar_string_is_error_not_char_iteration(tmp_path):
    """A user who forgets brackets shouldn't get 'channel v not in schema.channels' etc."""
    schema, events = _load_real_schema_events()
    body = VALID_MIN.replace("channels: [voice]", "channels: voice")
    p = _write(tmp_path, "salesforce/queue_based.md", body)
    bp = parse_blueprint(p)
    errors = validate(bp, schema, events)
    # Should get exactly ONE clear error about the type — not one per character
    type_errors = [e for e in errors if e.severity == "error" and "channels must be a YAML list" in e.message]
    assert len(type_errors) == 1
    # And there should be no spurious "channel 'v' not in ..." errors
    per_char_errors = [e for e in errors if e.severity == "error"
                       and "channel=" in e.message and len(e.message.split("channel=")[1].split(" ")[0]) <= 4]
    assert per_char_errors == []


def test_produces_events_as_scalar_string_is_error_not_char_iteration(tmp_path):
    schema, events = _load_real_schema_events()
    # Replace the multi-line list with a single quoted scalar — valid YAML, wrong type.
    body = VALID_MIN.replace(
        "produces_events: [interaction.received, interaction.routed, interaction.accepted,\n"
        "                  interaction.talk.start, interaction.talk.end,\n"
        "                  interaction.acw.start, interaction.acw.end,\n"
        "                  interaction.abandoned, interaction.completed,\n"
        "                  agent.login, agent.logout, agent.presence.change]",
        "produces_events: interaction.received",
    )
    p = _write(tmp_path, "salesforce/queue_based.md", body)
    bp = parse_blueprint(p)
    errors = validate(bp, schema, events)
    type_errors = [e for e in errors if e.severity == "error" and "produces_events must be a YAML list" in e.message]
    assert len(type_errors) == 1
