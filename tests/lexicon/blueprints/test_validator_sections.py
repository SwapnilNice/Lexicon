from pathlib import Path
import textwrap

from lexicon.blueprints.events import load_events
from lexicon.blueprints.parser import parse_blueprint
from lexicon.blueprints.schema import load_schema
from lexicon.blueprints.validator import validate

ROOT = Path(__file__).resolve().parents[3]


def _load_real():
    return (
        load_schema(ROOT / "ontology" / "blueprints" / "schema.yaml"),
        load_events(ROOT / "ontology" / "blueprints" / "events.yaml"),
    )


def _write(tmp_path, body):
    (tmp_path / "salesforce").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "salesforce" / "queue_based.md"
    p.write_text(textwrap.dedent(body).lstrip("\n"))
    return p


def _errs(bp_path):
    schema, events = _load_real()
    bp = parse_blueprint(bp_path)
    return validate(bp, schema, events)


# Same VALID_MIN as in test_validator_basics.py — copied here so tasks can be
# read independently.
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


def test_missing_required_section_is_error(tmp_path):
    body = VALID_MIN.replace("# Prerequisites\nx\n", "")
    p = _write(tmp_path, body)
    errors = _errs(p)
    assert any(e.severity == "error" and "Prerequisites" in e.message for e in errors)


def test_produces_events_without_subsection_is_error(tmp_path):
    # Remove the ### agent.presence.change subsection block (still declared in frontmatter).
    body = VALID_MIN.replace(
        "### agent.presence.change\n"
        "- **Recorded in:** X\n"
        "- **Trigger:** Y\n"
        "- **Prerequisite events:** agent.login\n",
        "",
    )
    p = _write(tmp_path, body)
    errors = _errs(p)
    assert any(e.severity == "error" and "agent.presence.change" in e.message
               and "subsection" in e.message.lower() for e in errors)


def test_orphan_event_subsection_is_error(tmp_path):
    # Insert an event subsection inside ACD event mapping that is not declared in produces_events.
    # Must be inserted inside the "# ACD event mapping" section (before # Validation)
    # so the parser captures it as an event subsection.
    body = VALID_MIN.replace(
        "# Validation\nx\n",
        "### interaction.consulted\n"
        "- **Recorded in:** X\n"
        "- **Trigger:** Y\n"
        "- **Prerequisite events:** interaction.accepted\n"
        "# Validation\nx\n",
    )
    p = _write(tmp_path, body)
    errors = _errs(p)
    assert any(e.severity == "error" and "interaction.consulted" in e.message
               and "orphan" in e.message.lower() for e in errors)


def test_missing_event_subsection_micro_field_is_error(tmp_path):
    # Drop the "Trigger" line from the interaction.received subsection.
    body = VALID_MIN.replace(
        "### interaction.received\n"
        "- **Recorded in:** X\n"
        "- **Trigger:** Y\n",
        "### interaction.received\n"
        "- **Recorded in:** X\n",
    )
    p = _write(tmp_path, body)
    errors = _errs(p)
    assert any(e.severity == "error" and "Trigger" in e.message
               and "interaction.received" in e.section for e in errors)


def test_object_footprint_unknown_concept_is_error(tmp_path):
    body = VALID_MIN.replace(
        "| routing_entity | Queue.Name | admin creates | n |",
        "| made_up_concept | Queue.Name | admin creates | n |",
    )
    p = _write(tmp_path, body)
    errors = _errs(p)
    assert any(e.severity == "error" and "made_up_concept" in e.message for e in errors)


def test_object_footprint_wrong_column_order_is_error(tmp_path):
    body = VALID_MIN.replace(
        "| Concept | Platform object.field | Populated when | Notes |\n"
        "|---|---|---|---|",
        "| Concept | Notes | Platform object.field | Populated when |\n"
        "|---|---|---|---|",
    )
    p = _write(tmp_path, body)
    errors = _errs(p)
    assert any(e.severity == "error" and ("column" in e.message.lower()
               or "footprint" in e.message.lower()) for e in errors)
