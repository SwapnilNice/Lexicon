# Flow Blueprint Capability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CRM-agnostic Flow Blueprint framework (schema + canonical ACD event taxonomy + validation tooling) plus one authored Salesforce queue-based reference blueprint. `python -m lexicon.blueprints validate` becomes a first-class CI check.

**Architecture:** New package `src/lexicon/blueprints/` with narrow single-responsibility modules (models / schema loader / events loader / parser / validator / indexer / CLI). Framework artifacts live at `ontology/blueprints/{schema,events}.yaml` and are consumed by every blueprint. One authored reference blueprint at `ontology/blueprints/salesforce/queue_based.md` validates the framework against a real platform. No pipeline coupling to sub-project A in v1.

**Tech Stack:** Python 3.10+, PyYAML (already installed), pytest. No new dependencies.

**Companion spec:** `docs/superpowers/specs/2026-08-09-flow-blueprint-design.md`. Read it first; every task below implements a specific part of that spec.

**Ground rules for the executor:**
- **TDD**: every code task writes the failing test first, then the minimum implementation to pass it.
- **No new dependencies.** Everything runs on the existing requirements.txt.
- **Existing tests must stay green.** After every task, `pytest -v` must pass 172+ tests. Any regression stops work.
- **Commit after every task.** Small, reviewable commits.
- **Framework code must not name any specific CRM.** Sub-project B2's success criterion #6: `grep -r salesforce src/lexicon/blueprints/` returns zero hits at the end. If you find yourself typing "salesforce" in framework code, stop — that name belongs in a blueprint file, not framework code.

---

## File map (locked in before tasks)

New under `ontology/blueprints/`:

```
ontology/blueprints/
  README.md                                    # authoring guide (Task 13)
  schema.yaml                                  # closed vocabulary (Task 3)
  events.yaml                                  # canonical ACD event taxonomy (Task 4)
  salesforce/
    queue_based.md                             # v1 reference blueprint (Task 12)
```

New under `src/lexicon/blueprints/`:

```
src/lexicon/blueprints/
  __init__.py                                  # empty (Task 1)
  models.py                                    # dataclasses (Task 2)
  schema.py                                    # loads schema.yaml (Task 5)
  events.py                                    # loads events.yaml + DAG validation (Task 6)
  parser.py                                    # blueprint.md → ParsedBlueprint (Task 7)
  validator.py                                 # ParsedBlueprint → list[ValidationError] (Tasks 8, 9)
  index.py                                     # discovers blueprint files (Task 10)
  cli.py                                       # list/show/validate commands (Task 11)
  __main__.py                                  # `python -m lexicon.blueprints` (Task 11)
```

New under `tests/lexicon/blueprints/`:

```
tests/lexicon/blueprints/
  test_models.py                               # Task 2
  test_schema.py                               # Task 5
  test_events.py                               # Task 6
  test_parser.py                               # Task 7
  test_validator_basics.py                     # Task 8
  test_validator_sections.py                   # Task 9
  test_index.py                                # Task 10
  test_cli.py                                  # Task 11
  test_reference_blueprint_validates.py        # Task 14
```

Unchanged: everything in sub-project A (`src/lexicon/discover/`, `tests/lexicon/discover/`, `ontology/canonical_wfm.yaml`, etc.).

---

## Task 1: Scaffold package + directory structure

**Files:**
- Create: `src/lexicon/blueprints/__init__.py`
- Create: `tests/lexicon/blueprints/__init__.py` — DO NOT create this; `tests/lexicon/` must remain a namespace package (see `tests/conftest.py` docstring)
- Create: `ontology/blueprints/salesforce/.gitkeep`

Task 1 is pure scaffolding. No Python logic beyond the empty `__init__.py`.

- [ ] **Step 1: Create the framework package init.**

```bash
touch "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon/src/lexicon/blueprints/__init__.py"
```

Verify the file exists and is exactly 0 bytes: `wc -c src/lexicon/blueprints/__init__.py` → prints `0 <path>`.

- [ ] **Step 2: Create the `ontology/blueprints/salesforce/` directory + `.gitkeep`.**

```bash
mkdir -p "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon/ontology/blueprints/salesforce"
touch "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon/ontology/blueprints/salesforce/.gitkeep"
```

- [ ] **Step 3: Confirm existing test suite still passes.**

```bash
cd "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon"
pytest -q 2>&1 | tail -3
```

Expected: `172 passed` (or higher — no regression).

- [ ] **Step 4: Commit.**

```bash
git add src/lexicon/blueprints/__init__.py ontology/blueprints/salesforce/.gitkeep
git commit -m "chore(blueprints): scaffold src/lexicon/blueprints package and ontology/blueprints/salesforce directory"
```

---

## Task 2: Data models

**Files:**
- Create: `src/lexicon/blueprints/models.py`
- Create: `tests/lexicon/blueprints/test_models.py`

Dataclasses used by parser, schema loader, events loader, and validator. Frozen where the object is a pure value.

- [ ] **Step 1: Write the failing test.** Create `tests/lexicon/blueprints/test_models.py`:

```python
from pathlib import Path

from lexicon.blueprints.models import (
    ParsedBlueprint, SchemaDef, EventTaxonomy, EventDef, PresenceStateDef,
    ValidationError,
)


def test_parsed_blueprint_shape():
    bp = ParsedBlueprint(
        path=Path("x.md"),
        frontmatter={"platform": "salesforce"},
        sections=[("Overview", "hi"), ("Prerequisites", "list")],
        event_subsections={"interaction.received": {"recorded_in": "X", "trigger": "Y",
                                                    "prerequisite_events": "none",
                                                    "caveats": "none"}},
    )
    assert bp.path == Path("x.md")
    assert bp.frontmatter["platform"] == "salesforce"
    assert bp.sections[0][0] == "Overview"


def test_schema_def_holds_closed_vocab():
    s = SchemaDef(
        platforms={"salesforce", "dynamics365"},
        routing_models={"queue_based", "skill_based"},
        channels={"voice", "chat"},
        required_sections=["Overview", "Prerequisites"],
        concept_vocabulary={"routing_entity", "interaction_record"},
        object_footprint_columns=["Concept", "Platform object.field"],
        event_subsection_fields={"Recorded in", "Trigger"},
    )
    assert "salesforce" in s.platforms
    assert s.required_sections == ["Overview", "Prerequisites"]


def test_event_def_defaults():
    e = EventDef(
        name="interaction.received",
        description="d",
        prerequisites=(),
        optional=False,
        projects_to_canonical_wfm=None,
        attributes={},
    )
    assert e.prerequisites == ()
    assert e.attributes == {}


def test_event_taxonomy_shape():
    t = EventTaxonomy(
        events={"interaction.received": EventDef(
            name="interaction.received", description="d",
            prerequisites=(), optional=False,
            projects_to_canonical_wfm=None, attributes={},
        )},
        presence_states={"ready": PresenceStateDef(name="ready", description="d")},
    )
    assert "interaction.received" in t.events
    assert t.presence_states["ready"].name == "ready"


def test_validation_error_shape():
    e = ValidationError(
        path=Path("x.md"),
        severity="error",
        section="frontmatter",
        message="missing 'platform'",
    )
    assert e.severity == "error"
    # ValidationError is frozen — attempting to mutate raises
    try:
        e.severity = "warning"
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("ValidationError should be frozen")
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'lexicon.blueprints.models'`.

- [ ] **Step 3: Implement `src/lexicon/blueprints/models.py`:**

```python
"""Dataclasses for the flow-blueprint framework.

These are the interfaces between stages. Every stage consumes and emits one
of these; no stage should invent its own shape.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class PresenceStateDef:
    name: str
    description: str


@dataclass(frozen=True)
class EventDef:
    name: str
    description: str
    prerequisites: tuple[str, ...]
    optional: bool
    projects_to_canonical_wfm: str | None
    attributes: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class EventTaxonomy:
    events: dict[str, EventDef]
    presence_states: dict[str, PresenceStateDef]


@dataclass(frozen=True)
class SchemaDef:
    platforms: set[str]
    routing_models: set[str]
    channels: set[str]
    required_sections: list[str]
    concept_vocabulary: set[str]
    object_footprint_columns: list[str]
    event_subsection_fields: set[str]


@dataclass(frozen=True)
class ParsedBlueprint:
    path: Path
    frontmatter: dict[str, Any]
    sections: list[tuple[str, str]]                 # [(header, body), ...] in source order
    event_subsections: dict[str, dict[str, str]]    # {event_name: {micro_field_name: value}}


@dataclass(frozen=True)
class ValidationError:
    path: Path
    severity: Literal["error", "warning"]
    section: str | None
    message: str
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_models.py -v
```

Expected: 5 pass.

- [ ] **Step 5: Confirm full suite is green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 172 + 5 = 177 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/blueprints/models.py tests/lexicon/blueprints/test_models.py
git commit -m "feat(blueprints): add data models for the framework"
```

---

## Task 3: Framework artifact — `schema.yaml`

**Files:**
- Create: `ontology/blueprints/schema.yaml`
- Create: `tests/lexicon/blueprints/test_schema_yaml_valid.py`

Author the closed-vocabulary YAML that every blueprint validates against.

- [ ] **Step 1: Write the failing test.** Create `tests/lexicon/blueprints/test_schema_yaml_valid.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_schema_yaml_valid.py -v
```

Expected: `FileNotFoundError` on `schema.yaml`.

- [ ] **Step 3: Author `ontology/blueprints/schema.yaml`:**

```yaml
# Flow Blueprint framework — closed vocabulary.
# Every blueprint's frontmatter and body validates against this file.
# See docs/superpowers/specs/2026-08-09-flow-blueprint-design.md §5, §8.4.

# ---------------------------------------------------------------------------
# Frontmatter closed enums
# ---------------------------------------------------------------------------
platforms:
  - salesforce
  - dynamics365
  - servicenow_cx
  - hubspot_service_hub
  - generic

routing_models:
  - queue_based
  - skill_based
  - presence_aware
  - overflow_escalation

channels:
  - voice
  - chat
  - messaging
  - email
  - case

# ---------------------------------------------------------------------------
# Body — required Markdown sections (in order)
# ---------------------------------------------------------------------------
required_sections:
  - "Overview"
  - "Prerequisites"
  - "Configuration steps"
  - "Object footprint"
  - "ACD event mapping"
  - "Validation"
# "Known traps" is OPTIONAL (recommended). Validator warns if absent, does not error.

# ---------------------------------------------------------------------------
# Object footprint table — closed Concept vocabulary
# ---------------------------------------------------------------------------
concept_vocabulary:
  - routing_entity
  - routing_entity_member
  - interaction_record
  - interaction_open
  - interaction_close
  - interaction_declined
  - interaction_expired
  - pending_routing
  - agent_presence
  - presence_state_type
  - assignment_rule

object_footprint_columns:
  - "Concept"
  - "Platform object.field"
  - "Populated when"
  - "Notes"

# ---------------------------------------------------------------------------
# ACD event mapping subsection micro-fields (per event)
# ---------------------------------------------------------------------------
event_subsection_fields:
  - "Recorded in"
  - "Trigger"
  - "Prerequisite events"
  - "Caveats"   # last one is optional; validator warns if absent, does not error
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_schema_yaml_valid.py -v
```

Expected: 4 pass.

- [ ] **Step 5: Confirm full suite is green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 177 + 4 = 181 pass.

- [ ] **Step 6: Commit.**

```bash
git add ontology/blueprints/schema.yaml tests/lexicon/blueprints/test_schema_yaml_valid.py
git commit -m "feat(blueprints): add schema.yaml with closed vocabulary"
```

---

## Task 4: Framework artifact — `events.yaml`

**Files:**
- Create: `ontology/blueprints/events.yaml`
- Create: `tests/lexicon/blueprints/test_events_yaml_valid.py`

Author the canonical ACD event taxonomy.

- [ ] **Step 1: Write the failing test.**

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_events_yaml_valid.py -v
```

Expected: FileNotFoundError.

- [ ] **Step 3: Author `ontology/blueprints/events.yaml`:**

```yaml
# Canonical ACD event taxonomy — vendor-neutral catalog of events a
# flow-configured platform can emit.
# See docs/superpowers/specs/2026-08-09-flow-blueprint-design.md §6.

meta:
  version: "1.0"
  description: "Vendor-neutral catalog of ACD events a flow-configured platform can emit."

# ---------------------------------------------------------------------------
# Presence state taxonomy — referenced by agent.presence.change attributes.
# ---------------------------------------------------------------------------
presence_states:
  ready:
    description: "Available to receive routed interactions."
  not_ready:
    description: "Logged in but not available (aux, away, break)."
  busy:
    description: "Actively handling one or more interactions."
  acw:
    description: "In after-call-work / wrap-up after an interaction."
  offline:
    description: "Logged out or ended session."

# ---------------------------------------------------------------------------
# Events. `prerequisites` form a DAG (validator enforces no cycles).
# `optional: true` events are per-blueprint choices; `optional: false` events
# must appear in every blueprint's produces_events list.
# `projects_to_canonical_wfm` is a hook for sub-project B4 — not consumed in v1.
# ---------------------------------------------------------------------------
events:
  interaction.received:
    description: "An interaction (call, chat, email, case) reaches the routing layer."
    prerequisites: []
    optional: false

  interaction.routed:
    description: "The routing layer assigns the interaction to an agent."
    prerequisites: [interaction.received]
    optional: false

  interaction.accepted:
    description: "The agent accepts the routed interaction."
    prerequisites: [interaction.routed]
    optional: false

  interaction.declined:
    description: "The agent explicitly declines the routed interaction."
    prerequisites: [interaction.routed]
    optional: true

  interaction.expired:
    description: "The routing layer times out waiting for agent acceptance."
    prerequisites: [interaction.routed]
    optional: true

  interaction.talk.start:
    description: "Talk time begins. For voice: line connected. For chat: first agent message."
    prerequisites: [interaction.accepted]
    optional: false
    projects_to_canonical_wfm: talk_time

  interaction.talk.end:
    description: "Talk time ends. Line disconnects (or hold begins) / agent closes session."
    prerequisites: [interaction.talk.start]
    optional: false

  interaction.hold.start:
    description: "Agent places the customer on hold."
    prerequisites: [interaction.talk.start]
    optional: true
    projects_to_canonical_wfm: hold_time

  interaction.hold.end:
    description: "Agent takes the customer off hold; talk time resumes."
    prerequisites: [interaction.hold.start]
    optional: true

  interaction.acw.start:
    description: "After-call-work begins. Talk time ends but the interaction is not yet closed."
    prerequisites: [interaction.talk.end]
    optional: false
    projects_to_canonical_wfm: acw_time

  interaction.acw.end:
    description: "Agent completes wrap-up; interaction closes."
    prerequisites: [interaction.acw.start]
    optional: false

  interaction.transferred:
    description: "The interaction is transferred to another agent, queue, or external number."
    prerequisites: [interaction.accepted]
    optional: true
    attributes:
      type:
        values: [warm, cold, blind]

  interaction.consulted:
    description: "Primary agent consults a second agent while keeping the customer on the interaction."
    prerequisites: [interaction.accepted]
    optional: true

  interaction.abandoned:
    description: "The customer disconnects before an agent accepts."
    prerequisites: [interaction.received]
    optional: false

  interaction.completed:
    description: "Terminal state: interaction is fully closed (post-ACW)."
    prerequisites: [interaction.acw.end]
    optional: false

  agent.login:
    description: "Agent begins a work session."
    prerequisites: []
    optional: false

  agent.logout:
    description: "Agent ends the work session."
    prerequisites: [agent.login]
    optional: false

  agent.presence.change:
    description: "Agent transitions between presence states."
    prerequisites: [agent.login]
    optional: false
    attributes:
      from_state:
        references: presence_states
      to_state:
        references: presence_states
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_events_yaml_valid.py -v
```

Expected: 5 pass.

- [ ] **Step 5: Confirm full suite is green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 181 + 5 = 186 pass.

- [ ] **Step 6: Commit.**

```bash
git add ontology/blueprints/events.yaml tests/lexicon/blueprints/test_events_yaml_valid.py
git commit -m "feat(blueprints): add events.yaml with canonical ACD event taxonomy"
```

---

## Task 5: Schema loader (`schema.py`)

**Files:**
- Create: `src/lexicon/blueprints/schema.py`
- Create: `tests/lexicon/blueprints/test_schema.py`

Loads `ontology/blueprints/schema.yaml` into a `SchemaDef` dataclass.

- [ ] **Step 1: Write the failing test.**

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_schema.py -v
```

Expected: `ModuleNotFoundError: No module named 'lexicon.blueprints.schema'`.

- [ ] **Step 3: Implement `src/lexicon/blueprints/schema.py`:**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_schema.py -v
```

Expected: 4 pass.

- [ ] **Step 5: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 186 + 4 = 190 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/blueprints/schema.py tests/lexicon/blueprints/test_schema.py
git commit -m "feat(blueprints): add schema loader with validation"
```

---

## Task 6: Events loader + DAG validator (`events.py`)

**Files:**
- Create: `src/lexicon/blueprints/events.py`
- Create: `tests/lexicon/blueprints/test_events.py`

Loads `ontology/blueprints/events.yaml` into `EventTaxonomy`. Validates the prerequisite DAG (no cycles, no orphan prerequisites, valid attribute references).

- [ ] **Step 1: Write the failing test.**

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_events.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `src/lexicon/blueprints/events.py`:**

```python
"""Loader + DAG validator for ontology/blueprints/events.yaml."""
from __future__ import annotations
from pathlib import Path
import yaml

from .models import EventDef, EventTaxonomy, PresenceStateDef


class EventsError(ValueError):
    pass


def load_events(path: Path) -> EventTaxonomy:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    for key in ("meta", "presence_states", "events"):
        if key not in raw:
            raise EventsError(f"events.yaml missing top-level key {key!r}")
    presence_states = {
        name: PresenceStateDef(name=name, description=spec.get("description", ""))
        for name, spec in (raw["presence_states"] or {}).items()
    }
    events = {}
    for name, spec in (raw["events"] or {}).items():
        events[name] = EventDef(
            name=name,
            description=spec.get("description", ""),
            prerequisites=tuple(spec.get("prerequisites") or []),
            optional=bool(spec.get("optional", False)),
            projects_to_canonical_wfm=spec.get("projects_to_canonical_wfm"),
            attributes=spec.get("attributes") or {},
        )
    return EventTaxonomy(events=events, presence_states=presence_states)


def validate_taxonomy(t: EventTaxonomy) -> list[str]:
    """Return a list of human-readable error strings. Empty list = valid."""
    errors: list[str] = []
    names = set(t.events)

    # 1. Every prerequisite must exist in events.
    for e in t.events.values():
        for pre in e.prerequisites:
            if pre not in names:
                errors.append(f"event {e.name!r} depends on {pre!r} which is not defined")

    # 2. No cycles.
    # DFS with recursion stack. Only follow prerequisites that actually resolve
    # (guarded by check 1 above so we skip missing ones to focus this error on cycles).
    color: dict[str, str] = {n: "white" for n in names}

    def dfs(n: str, stack: list[str]) -> None:
        color[n] = "gray"
        for pre in t.events[n].prerequisites:
            if pre not in names:
                continue
            if color[pre] == "gray":
                cycle = stack + [n, pre]
                errors.append(f"cycle detected in prerequisites: {' -> '.join(cycle)}")
                return
            if color[pre] == "white":
                dfs(pre, stack + [n])
        color[n] = "black"

    for n in names:
        if color[n] == "white":
            dfs(n, [])

    # 3. Attribute references must target existing taxonomies.
    valid_taxonomies = {"presence_states"}
    for e in t.events.values():
        for attr_name, attr_spec in e.attributes.items():
            ref = attr_spec.get("references") if isinstance(attr_spec, dict) else None
            if ref is not None and ref not in valid_taxonomies:
                errors.append(
                    f"event {e.name!r} attribute {attr_name!r} references "
                    f"{ref!r} which is not a valid taxonomy (expected one of {sorted(valid_taxonomies)})"
                )

    return errors
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_events.py -v
```

Expected: 6 pass.

- [ ] **Step 5: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 190 + 6 = 196 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/blueprints/events.py tests/lexicon/blueprints/test_events.py
git commit -m "feat(blueprints): add events loader + DAG validator"
```

---

## Task 7: Blueprint parser (`parser.py`)

**Files:**
- Create: `src/lexicon/blueprints/parser.py`
- Create: `tests/lexicon/blueprints/test_parser.py`

Parses one blueprint.md into `ParsedBlueprint(frontmatter, sections, event_subsections)`.

- [ ] **Step 1: Write the failing test.**

```python
from pathlib import Path
import textwrap
import pytest

from lexicon.blueprints.parser import parse_blueprint, ParserError


def _write(tmp_path, body):
    p = tmp_path / "bp.md"
    p.write_text(textwrap.dedent(body).lstrip("\n"))
    return p


def test_parses_frontmatter_and_sections(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: salesforce
        routing_model: queue_based
        ---
        # Overview
        Words.

        # Prerequisites
        - Item 1
    """)
    bp = parse_blueprint(p)
    assert bp.frontmatter["platform"] == "salesforce"
    assert bp.frontmatter["routing_model"] == "queue_based"
    assert [h for h, _ in bp.sections] == ["Overview", "Prerequisites"]
    overview_body = dict(bp.sections)["Overview"].strip()
    assert overview_body == "Words."


def test_parses_event_subsections(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: salesforce
        ---
        # ACD event mapping

        ### interaction.received
        - **Recorded in:** `PSR`
        - **Trigger:** interaction arrives
        - **Prerequisite events:** none
        - **Caveats:** none

        ### interaction.routed
        - **Recorded in:** `AgentWork`
        - **Trigger:** router assigns
        - **Prerequisite events:** interaction.received
        - **Caveats:** none
    """)
    bp = parse_blueprint(p)
    assert set(bp.event_subsections.keys()) == {"interaction.received", "interaction.routed"}
    assert bp.event_subsections["interaction.received"]["Recorded in"] == "`PSR`"
    assert bp.event_subsections["interaction.routed"]["Prerequisite events"] == "interaction.received"


def test_missing_frontmatter_raises(tmp_path):
    p = _write(tmp_path, """
        # Overview
        No frontmatter here.
    """)
    with pytest.raises(ParserError, match="frontmatter"):
        parse_blueprint(p)


def test_malformed_frontmatter_yaml_raises(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: [salesforce
        ---
        # Overview
        Body.
    """)
    with pytest.raises(ParserError, match="YAML"):
        parse_blueprint(p)


def test_hash_inside_code_fence_not_treated_as_header(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: salesforce
        ---
        # Overview

        Some content with a code block:

        ```python
        # This is a Python comment, not a section header.
        x = 1
        ```

        More overview text.
    """)
    bp = parse_blueprint(p)
    assert [h for h, _ in bp.sections] == ["Overview"]
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_parser.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `src/lexicon/blueprints/parser.py`:**

```python
"""Parse a blueprint.md file into a ParsedBlueprint.

Frontmatter is a YAML block between --- markers at the top of the file.
Sections are `# Section Name` lines followed by their body.
Event subsections are `### <event.name>` lines inside "ACD event mapping"
with bullet items formatted as `- **<Micro-field>:** <value>`.

Code fences (``` ... ```) are respected — `#` inside a code fence is not a
section header.
"""
from __future__ import annotations
from pathlib import Path
import re

import yaml

from .models import ParsedBlueprint


class ParserError(ValueError):
    pass


_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_SECTION_HEADER_RE = re.compile(r"^# (.+)$")
_EVENT_HEADER_RE = re.compile(r"^### (.+)$")
_MICRO_FIELD_RE = re.compile(r"^- \*\*(.+?):\*\*\s+(.+)$")
_CODE_FENCE_RE = re.compile(r"^```")


def parse_blueprint(path: Path) -> ParsedBlueprint:
    text = Path(path).read_text()
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ParserError(f"{path.name}: missing frontmatter (expected --- ... --- at top)")
    fm_text, body = m.group(1), m.group(2)
    try:
        frontmatter = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise ParserError(f"{path.name}: malformed YAML frontmatter: {e}")

    sections: list[tuple[str, str]] = []
    event_subsections: dict[str, dict[str, str]] = {}

    current_section: str | None = None
    current_section_lines: list[str] = []
    current_event: str | None = None
    in_code_fence = False

    def flush_section():
        if current_section is not None:
            sections.append((current_section, "\n".join(current_section_lines)))

    for line in body.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_code_fence = not in_code_fence
            current_section_lines.append(line)
            continue
        if in_code_fence:
            current_section_lines.append(line)
            continue

        h = _SECTION_HEADER_RE.match(line)
        if h:
            flush_section()
            current_section = h.group(1).strip()
            current_section_lines = []
            current_event = None
            continue

        eh = _EVENT_HEADER_RE.match(line)
        if eh and current_section == "ACD event mapping":
            current_event = eh.group(1).strip()
            event_subsections[current_event] = {}
            current_section_lines.append(line)
            continue

        if current_event is not None:
            mm = _MICRO_FIELD_RE.match(line)
            if mm:
                event_subsections[current_event][mm.group(1).strip()] = mm.group(2).strip()
            current_section_lines.append(line)
            continue

        current_section_lines.append(line)

    flush_section()

    return ParsedBlueprint(
        path=Path(path),
        frontmatter=frontmatter,
        sections=sections,
        event_subsections=event_subsections,
    )
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_parser.py -v
```

Expected: 5 pass.

- [ ] **Step 5: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 196 + 5 = 201 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/blueprints/parser.py tests/lexicon/blueprints/test_parser.py
git commit -m "feat(blueprints): add blueprint parser (frontmatter + sections + event subsections)"
```

---

## Task 8: Validator — frontmatter, closed enums, file path (`validator.py` part 1)

**Files:**
- Create: `src/lexicon/blueprints/validator.py`
- Create: `tests/lexicon/blueprints/test_validator_basics.py`

First half of the validator: frontmatter presence, closed-enum values, file path matches frontmatter, `produces_events` references valid events.

- [ ] **Step 1: Write the failing test.**

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_validator_basics.py -v
```

Expected: ModuleNotFoundError on `lexicon.blueprints.validator`.

- [ ] **Step 3: Implement `src/lexicon/blueprints/validator.py`:**

```python
"""Blueprint validator. Checks all rules from spec §5.6."""
from __future__ import annotations
from datetime import date, timedelta
from pathlib import Path

from .models import EventTaxonomy, ParsedBlueprint, SchemaDef, ValidationError


REQUIRED_FRONTMATTER_KEYS = {
    "platform", "platform_display_name", "routing_model", "channels",
    "version", "last_verified", "platform_version_verified_against",
    "authored_by", "produces_events",
}


def _err(path: Path, section: str | None, message: str) -> ValidationError:
    return ValidationError(path=path, severity="error", section=section, message=message)


def _warn(path: Path, section: str | None, message: str) -> ValidationError:
    return ValidationError(path=path, severity="warning", section=section, message=message)


def validate(bp: ParsedBlueprint, schema: SchemaDef, events: EventTaxonomy) -> list[ValidationError]:
    errors: list[ValidationError] = []
    fm = bp.frontmatter

    # --- 1. Required frontmatter keys ---
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in fm:
            errors.append(_err(bp.path, "frontmatter", f"missing required key {key!r}"))

    # --- 2. Closed enums ---
    if fm.get("platform") is not None and fm["platform"] not in schema.platforms:
        errors.append(_err(
            bp.path, "frontmatter",
            f"platform={fm['platform']!r} not in schema.platforms ({sorted(schema.platforms)})",
        ))
    if fm.get("routing_model") is not None and fm["routing_model"] not in schema.routing_models:
        errors.append(_err(
            bp.path, "frontmatter",
            f"routing_model={fm['routing_model']!r} not in schema.routing_models ({sorted(schema.routing_models)})",
        ))
    for ch in fm.get("channels") or []:
        if ch not in schema.channels:
            errors.append(_err(
                bp.path, "frontmatter",
                f"channel={ch!r} not in schema.channels ({sorted(schema.channels)})",
            ))

    # --- 3. File path matches frontmatter ---
    expected_stem = fm.get("routing_model")
    expected_parent = fm.get("platform")
    if expected_stem and expected_parent:
        if bp.path.stem != expected_stem or bp.path.parent.name != expected_parent:
            errors.append(_err(
                bp.path, "frontmatter",
                f"file path {bp.path.parent.name}/{bp.path.name} does not match "
                f"frontmatter platform={expected_parent!r} routing_model={expected_stem!r}",
            ))

    # --- 4. produces_events references valid events ---
    for ev in fm.get("produces_events") or []:
        if ev not in events.events:
            errors.append(_err(
                bp.path, "frontmatter",
                f"produces_events contains {ev!r} which is not in events.yaml",
            ))

    # --- 5. last_verified freshness (warning at 6mo, error at 12mo) ---
    lv = fm.get("last_verified")
    if isinstance(lv, date):
        today = date.today()
        age = today - lv
        if age > timedelta(days=365):
            errors.append(_err(
                bp.path, "frontmatter",
                f"last_verified={lv} is more than 12 months old — blueprint likely stale",
            ))
        elif age > timedelta(days=182):
            errors.append(_warn(
                bp.path, "frontmatter",
                f"last_verified={lv} is more than 6 months old — consider re-verifying",
            ))

    return errors
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_validator_basics.py -v
```

Expected: 5 pass.

- [ ] **Step 5: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 201 + 5 = 206 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/blueprints/validator.py tests/lexicon/blueprints/test_validator_basics.py
git commit -m "feat(blueprints): validator — frontmatter, closed enums, file path, event references"
```

---

## Task 9: Validator — sections, event subsections, object footprint (`validator.py` part 2)

**Files:**
- Modify: `src/lexicon/blueprints/validator.py`
- Create: `tests/lexicon/blueprints/test_validator_sections.py`

Second half: required sections present, event subsection completeness, orphan subsections, object footprint table.

- [ ] **Step 1: Write the failing test.**

```python
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
    # Add an event subsection not declared in produces_events.
    body = VALID_MIN + textwrap.dedent("""
        ### interaction.consulted
        - **Recorded in:** X
        - **Trigger:** Y
        - **Prerequisite events:** interaction.accepted
    """)
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_validator_sections.py -v
```

Expected: 6 fail (each test's assertions fail because validator doesn't implement these rules yet).

- [ ] **Step 3: Extend `src/lexicon/blueprints/validator.py`.** This step has two parts.

**Part A** — insert the following new checks INSIDE `validate()`, immediately before the existing `return errors` line (i.e., they run after all the Task 8 checks):

```python
    # --- 6. Required sections present, in order (no order check for v1 — just presence) ---
    section_names = [h for h, _ in bp.sections]
    for req in schema.required_sections:
        if req not in section_names:
            errors.append(_err(bp.path, req, f"missing required section {req!r}"))

    # --- 7. produces_events ↔ event subsections one-to-one ---
    declared = set(fm.get("produces_events") or [])
    found = set(bp.event_subsections.keys())
    for missing_ev in declared - found:
        errors.append(_err(
            bp.path, "ACD event mapping",
            f"produces_events lists {missing_ev!r} but no ### {missing_ev} subsection found",
        ))
    for orphan_ev in found - declared:
        errors.append(_err(
            bp.path, f"### {orphan_ev}",
            f"orphan event subsection {orphan_ev!r}: not declared in produces_events",
        ))

    # --- 8. Each event subsection has required micro-fields ---
    required_fields = {f for f in schema.event_subsection_fields if f != "Caveats"}
    for ev, fields in bp.event_subsections.items():
        for req in required_fields:
            if req not in fields:
                errors.append(_err(
                    bp.path, f"### {ev}",
                    f"missing required micro-field {req!r} in event subsection {ev!r}",
                ))
        if "Caveats" not in fields:
            errors.append(_warn(
                bp.path, f"### {ev}",
                f"missing optional micro-field 'Caveats' in event subsection {ev!r}",
            ))

    # --- 9. Object footprint table ---
    footprint_body = dict(bp.sections).get("Object footprint", "")
    if footprint_body.strip():
        errors.extend(_validate_object_footprint(bp.path, footprint_body, schema))
```

(The existing `return errors` line follows this block — do not duplicate it.)

**Part B** — add the following helper function at MODULE LEVEL in the same file, after the `validate()` function definition ends:

```python
def _validate_object_footprint(path: Path, body: str, schema: SchemaDef) -> list[ValidationError]:
    """Validate the Object footprint Markdown table's columns and Concept column values."""
    errors: list[ValidationError] = []
    lines = [line for line in body.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        errors.append(_err(path, "Object footprint", "no Markdown table found"))
        return errors

    def cells(line: str) -> list[str]:
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        return parts

    header_cells = cells(lines[0])
    if header_cells != schema.object_footprint_columns:
        errors.append(_err(
            path, "Object footprint",
            f"columns {header_cells} do not match schema {schema.object_footprint_columns}",
        ))
        return errors

    # Data rows start after the separator line (line[1]).
    for i, row in enumerate(lines[2:], start=1):
        row_cells = cells(row)
        if len(row_cells) != len(schema.object_footprint_columns):
            errors.append(_err(
                path, "Object footprint",
                f"row {i}: has {len(row_cells)} cells, expected {len(schema.object_footprint_columns)}",
            ))
            continue
        concept = row_cells[0]
        if concept not in schema.concept_vocabulary:
            errors.append(_err(
                path, "Object footprint",
                f"row {i}: concept {concept!r} not in concept_vocabulary "
                f"({sorted(schema.concept_vocabulary)})",
            ))
    return errors
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_validator_sections.py -v
```

Expected: 6 pass.

- [ ] **Step 5: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 206 + 6 = 212 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/blueprints/validator.py tests/lexicon/blueprints/test_validator_sections.py
git commit -m "feat(blueprints): validator — sections, event subsections, orphans, footprint table"
```

---

## Task 10: Blueprint indexer (`index.py`)

**Files:**
- Create: `src/lexicon/blueprints/index.py`
- Create: `tests/lexicon/blueprints/test_index.py`

Enumerates blueprint files on disk. Skips files without `platform:` in their first ~20 lines (so a `README.md` in a platform directory is silently ignored).

- [ ] **Step 1: Write the failing test.**

```python
from pathlib import Path
import textwrap

from lexicon.blueprints.index import discover


def test_discovers_blueprint_files(tmp_path):
    (tmp_path / "salesforce").mkdir()
    (tmp_path / "salesforce" / "queue_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        routing_model: queue_based
        ---
        # Overview
    """))
    (tmp_path / "salesforce" / "skill_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        routing_model: skill_based
        ---
        # Overview
    """))
    found = discover(tmp_path)
    names = sorted(p.name for p in found)
    assert names == ["queue_based.md", "skill_based.md"]


def test_skips_files_without_platform_frontmatter(tmp_path):
    (tmp_path / "salesforce").mkdir()
    (tmp_path / "salesforce" / "queue_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        ---
        # Overview
    """))
    (tmp_path / "salesforce" / "README.md").write_text("# Not a blueprint\nJust docs.\n")
    found = discover(tmp_path)
    assert [p.name for p in found] == ["queue_based.md"]


def test_returns_empty_on_missing_dir(tmp_path):
    assert discover(tmp_path / "does_not_exist") == []
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_index.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `src/lexicon/blueprints/index.py`:**

```python
"""Discover blueprint files on disk.

A blueprint file is a `.md` file with YAML frontmatter that contains a
`platform:` key. Files without frontmatter (e.g., README.md) are skipped.
"""
from __future__ import annotations
from pathlib import Path


def discover(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    out: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        try:
            head = "".join(path.open("r").readlines()[:20])
        except OSError:
            continue
        if head.startswith("---") and "\nplatform:" in head:
            out.append(path)
    return out
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_index.py -v
```

Expected: 3 pass.

- [ ] **Step 5: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 212 + 3 = 215 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/blueprints/index.py tests/lexicon/blueprints/test_index.py
git commit -m "feat(blueprints): add blueprint indexer"
```

---

## Task 11: CLI + `__main__.py`

**Files:**
- Create: `src/lexicon/blueprints/cli.py`
- Create: `src/lexicon/blueprints/__main__.py`
- Create: `tests/lexicon/blueprints/test_cli.py`

Three subcommands: `list`, `show <platform> <routing_model>`, `validate [<path>]`.

- [ ] **Step 1: Write the failing test.**

```python
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def _root():
    return Path(__file__).resolve().parents[3]


def _seed(tmp_path):
    (tmp_path / "salesforce").mkdir()
    (tmp_path / "salesforce" / "queue_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        platform_display_name: "Salesforce"
        routing_model: queue_based
        channels: [voice]
        version: "1.0"
        last_verified: 2026-08-09
        platform_version_verified_against: "Spring '26"
        authored_by: "T"
        produces_events: [interaction.received]
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

        # Validation
        x
    """).lstrip("\n"))
    return tmp_path


def _invoke(*args, cwd, blueprints_dir):
    env = {**os.environ, "PYTHONPATH": str(_root() / "src")}
    return subprocess.run(
        [sys.executable, "-m", "lexicon.blueprints",
         *args, "--blueprints-dir", str(blueprints_dir)],
        capture_output=True, text=True, cwd=str(cwd), env=env,
    )


def test_list_shows_seeded_blueprint(tmp_path):
    bd = _seed(tmp_path)
    r = _invoke("list", cwd=_root(), blueprints_dir=bd)
    assert r.returncode == 0, r.stderr
    assert "salesforce" in r.stdout
    assert "queue_based" in r.stdout


def test_show_prints_the_blueprint(tmp_path):
    bd = _seed(tmp_path)
    r = _invoke("show", "salesforce", "queue_based", cwd=_root(), blueprints_dir=bd)
    assert r.returncode == 0, r.stderr
    assert "# Overview" in r.stdout


def test_validate_all_passes_on_a_seeded_blueprint(tmp_path):
    """This uses the framework's real schema.yaml + events.yaml but a synthesized
    blueprint that misses many produces_events. Validator will error on those,
    but the goal here is just to prove the CLI plumbing works — exit non-zero and
    print errors is the correct behavior.
    """
    bd = _seed(tmp_path)
    r = _invoke("validate", cwd=_root(), blueprints_dir=bd)
    # Exit 1 because the seeded blueprint is minimal and won't satisfy all
    # required-event checks. The important assertion is that some errors are
    # printed (not a Python traceback).
    assert r.returncode != 0
    assert "error" in r.stdout.lower() or "error" in r.stderr.lower()


def test_validate_missing_blueprints_dir_prints_message(tmp_path):
    r = _invoke("validate", cwd=_root(), blueprints_dir=tmp_path / "does_not_exist")
    # 0 blueprints found — validator has nothing to check; exits 0.
    assert r.returncode == 0
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/blueprints/test_cli.py -v
```

Expected: subprocess fails because `lexicon.blueprints` has no `__main__`.

- [ ] **Step 3: Implement `src/lexicon/blueprints/cli.py`:**

```python
"""`python -m lexicon.blueprints` entrypoint.

Subcommands:
  list                        — enumerate discovered blueprints
  show <platform> <routing>   — print a specific blueprint to stdout
  validate [<path>]           — validate all blueprints (or one path)

Flags:
  --blueprints-dir <path>     — default: ontology/blueprints/
  --schema-path <path>        — default: ontology/blueprints/schema.yaml
  --events-path <path>        — default: ontology/blueprints/events.yaml
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .events import load_events, validate_taxonomy
from .index import discover
from .parser import parse_blueprint, ParserError
from .schema import load_schema
from .validator import validate


ROOT = Path(__file__).resolve().parents[3]


def _paths(args) -> tuple[Path, Path, Path]:
    bd = Path(args.blueprints_dir) if args.blueprints_dir else ROOT / "ontology" / "blueprints"
    sp = Path(args.schema_path) if args.schema_path else bd / "schema.yaml"
    ep = Path(args.events_path) if args.events_path else bd / "events.yaml"
    return bd, sp, ep


def cmd_list(args) -> int:
    bd, _, _ = _paths(args)
    files = discover(bd)
    if not files:
        print(f"(no blueprints found under {bd})")
        return 0
    print(f"{'PLATFORM':16} {'ROUTING':20} {'VERSION':8} VERIFIED")
    for path in files:
        import yaml
        head = "".join(path.open("r").readlines()[:40])
        # crude — but we don't need full parse for a listing
        try:
            fm_text = head.split("---")[1]
            fm = yaml.safe_load(fm_text) or {}
        except (IndexError, yaml.YAMLError):
            fm = {}
        print(f"{fm.get('platform',''):16} {fm.get('routing_model',''):20} "
              f"{str(fm.get('version','')):8} {fm.get('last_verified','')}")
    return 0


def cmd_show(args) -> int:
    bd, _, _ = _paths(args)
    path = bd / args.platform / f"{args.routing_model}.md"
    if not path.exists():
        print(f"blueprint not found: {path}", file=sys.stderr)
        return 2
    sys.stdout.write(path.read_text())
    return 0


def cmd_validate(args) -> int:
    bd, sp, ep = _paths(args)
    if not sp.exists() or not ep.exists():
        print(f"framework not initialized: {sp} or {ep} missing", file=sys.stderr)
        return 2
    schema = load_schema(sp)
    taxonomy = load_events(ep)
    tax_errors = validate_taxonomy(taxonomy)
    if tax_errors:
        print("events.yaml has errors:")
        for e in tax_errors:
            print(f"  [error] {e}")
        return 1

    if args.path:
        files = [Path(args.path)]
    else:
        files = discover(bd)
    if not files:
        return 0

    total_errors = 0
    for path in files:
        try:
            bp = parse_blueprint(path)
        except ParserError as e:
            print(f"✗ {path}")
            print(f"  [error] {e}")
            total_errors += 1
            continue
        errs = validate(bp, schema, taxonomy)
        errors_only = [e for e in errs if e.severity == "error"]
        warnings = [e for e in errs if e.severity == "warning"]
        if errors_only:
            print(f"✗ {path}")
            for e in errors_only:
                s = f" ({e.section})" if e.section else ""
                print(f"  [error]{s} {e.message}")
            total_errors += 1
        else:
            print(f"✓ {path}")
        for w in warnings:
            s = f" ({w.section})" if w.section else ""
            print(f"  [warning]{s} {w.message}")
    if total_errors:
        print(f"\n✗ {total_errors} blueprint(s) failed validation")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser("lexicon.blueprints")
    ap.add_argument("--blueprints-dir", default=None)
    ap.add_argument("--schema-path", default=None)
    ap.add_argument("--events-path", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    sp = sub.add_parser("show")
    sp.add_argument("platform")
    sp.add_argument("routing_model")

    vp = sub.add_parser("validate")
    vp.add_argument("path", nargs="?", default=None)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "show":
        return cmd_show(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    return 2
```

- [ ] **Step 4: Create `src/lexicon/blueprints/__main__.py`:**

```python
from .cli import main
raise SystemExit(main())
```

- [ ] **Step 5: Run tests to verify they pass.**

```bash
pytest tests/lexicon/blueprints/test_cli.py -v
```

Expected: 4 pass.

- [ ] **Step 6: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 215 + 4 = 219 pass.

- [ ] **Step 7: Commit.**

```bash
git add src/lexicon/blueprints/cli.py src/lexicon/blueprints/__main__.py tests/lexicon/blueprints/test_cli.py
git commit -m "feat(blueprints): add CLI (list/show/validate) + __main__ entrypoint"
```

---

## Task 12: Salesforce reference blueprint

**Files:**
- Create: `ontology/blueprints/salesforce/queue_based.md`

Author the one v1 reference blueprint. This is the largest single artifact in the plan. Follows the schema from `schema.yaml` and references events from `events.yaml`.

- [ ] **Step 1: Author the file.** Create `ontology/blueprints/salesforce/queue_based.md` with the following content:

````markdown
---
platform: salesforce
platform_display_name: "Salesforce Service Cloud"
routing_model: queue_based
channels: [voice, chat, messaging, email, case]
version: "1.0"
last_verified: 2026-08-09
platform_version_verified_against: "Spring '26"
authored_by: "Swapnil Zade"
produces_events:
  - interaction.received
  - interaction.routed
  - interaction.accepted
  - interaction.declined
  - interaction.expired
  - interaction.talk.start
  - interaction.talk.end
  - interaction.acw.start
  - interaction.acw.end
  - interaction.transferred
  - interaction.abandoned
  - interaction.completed
  - agent.login
  - agent.logout
  - agent.presence.change
tags: [omni-channel, service-cloud]
---

# Overview

Salesforce Omni-Channel with **queue-based routing**: interactions (Cases, Chat sessions, Voice calls, Messaging sessions) land in one of N Queues; agents whose Presence Configuration matches the Queue's Routing Configuration are eligible to receive routed work in a pull-style model.

**When to use this configuration:**
- You want a shared inbox model where agents pull from a queue.
- Routing decisions are primarily "which queue", not "which agent has skill X".
- You have a small-to-medium number of routing distinctions (< ~20 queues per org is comfortable).

**When to use something else:**
- Need attribute-based matching (language, tier, product) → use the `skill_based` blueprint instead.
- Need per-agent capacity overlays and real-time availability → layer the `presence_aware` blueprint on top.
- Need fallback / spillover behavior when a queue can't handle → layer the `overflow_escalation` blueprint on top.

# Prerequisites

- [ ] Salesforce Service Cloud license (Enterprise, Performance, Unlimited, or Developer)
- [ ] Omni-Channel enabled — Setup → Feature Settings → Service → Omni-Channel Settings → check "Enable Omni-Channel"
- [ ] Admin permissions: "Customize Application", "Manage Users", "Manage Public Groups"
- [ ] For voice: Service Cloud Voice add-on license + a configured Contact Center
- [ ] For messaging: Digital Engagement license + at least one Messaging Channel enabled
- [ ] For chat: Live Agent / Embedded Service configured (deprecated but common)

# Configuration steps

1. **Enable Omni-Channel.** Setup → Feature Settings → Service → Omni-Channel Settings → check "Enable Omni-Channel" → Save.
2. **Create Service Channels.** Setup → Feature Settings → Service → Omni-Channel → Service Channels → New. Create one per interaction type you route (e.g., "Case Channel" with Salesforce Object = Case; "Voice Channel" with Salesforce Object = VoiceCall; "Messaging Channel" with Salesforce Object = MessagingSession).
3. **Create Presence Configurations.** Setup → Feature Settings → Service → Omni-Channel → Presence Configurations → New. Define agent capacity per channel (e.g., "up to 5 cases + 1 voice call") and auto-accept behavior.
4. **Create Presence Statuses.** Setup → Feature Settings → Service → Omni-Channel → Presence Statuses → New. At minimum: one "Available" status (StatusOption = Online) linked to your Presence Config's Service Channels; one "Away" and one "Offline" (StatusOption = Away).
5. **Create Queues.** Setup → Users → Queues → New. For each queue:
   - Label + Queue Name
   - Supported Objects: match the Service Channel's SObject (Case, MessagingSession, VoiceCall, etc.)
   - Queue Members: add Users or Public Groups (nested groups are allowed but see Known traps)
6. **Create Omni-Channel Routing Configuration.** Setup → Feature Settings → Service → Omni-Channel → Routing Configurations → New. Set:
   - Routing Model: `Least Active` (assigns to the agent with fewest active items) or `Most Available` (uses spare capacity first)
   - Push Time-Out: seconds before auto-reroute if agent doesn't accept (typical: 30–60s)
7. **Bind Routing Configuration to each Queue.** From the Queue detail page → Routing Configuration lookup → select the Routing Configuration from step 6.
8. **Assign Presence Configuration to agent Users.** User record → Presence Configuration lookup → select the Presence Configuration. Save.
9. **Verify Omni-Channel widget appears** for the agent (utility bar item). If not: check the User's profile has Omni-Channel enabled and the app has the utility bar item configured.

# Object footprint

| Concept | Platform object.field | Populated when | Notes |
|---|---|---|---|
| routing_entity | Group (Type='Queue').Name | Admin creates a Queue | Queues are `Group` records with `Type='Queue'` |
| routing_entity_member | GroupMember.UserOrGroupId | Admin adds a member | Direct User or nested Public Group |
| interaction_record | AgentWork | Interaction is routed | One AgentWork per assignment attempt |
| interaction_open | AgentWork.AcceptDateTime | Agent accepts | Null until acceptance |
| interaction_close | AgentWork.EndDateTime | Agent closes work | ACW may follow via CloseDateTime |
| interaction_declined | AgentWork.DeclineDateTime | Agent declines | AgentWork stays; new attempt spawned |
| pending_routing | PendingServiceRouting | Interaction awaits routing | Deleted once routed — see Known traps |
| agent_presence | UserServicePresence | Agent presence changes | One row per state transition |
| presence_state_type | ServicePresenceStatus | Admin defines a status | StatusOption enum: Online/Away/Offline |
| assignment_rule | OmniChannelRoutingConfig | Admin creates routing config | ModelType='LeastActive' or 'MostAvailable' |

# ACD event mapping

### interaction.received
- **Recorded in:** `PendingServiceRouting` (row is created)
- **Trigger:** A routable object (Case, MessagingSession, VoiceCall, Chat_Transcript) is submitted to a Queue that has an Omni-Channel Routing Configuration bound.
- **Prerequisite events:** none
- **Caveats:** PSR rows are transient — deleted once routed. See Known traps.

### interaction.routed
- **Recorded in:** `AgentWork` (row created; UserId set)
- **Trigger:** OmniChannelRoutingConfig assigns the PSR to an agent per the routing model (Least Active / Most Available).
- **Prerequisite events:** interaction.received
- **Caveats:** For pull-model queues, "routed" is when the agent's queue view refreshes and the item becomes visible in Omni-Channel.

### interaction.accepted
- **Recorded in:** `AgentWork.AcceptDateTime`
- **Trigger:** Agent clicks Accept on the Omni-Channel widget.
- **Prerequisite events:** interaction.routed
- **Caveats:** For voice interactions, AcceptDateTime is the Omni-Channel accept — not when the voice line actually connects. See Known traps.

### interaction.declined
- **Recorded in:** `AgentWork.DeclineDateTime` (and Status = 'Declined')
- **Trigger:** Agent clicks Decline within the Push Time-Out window.
- **Prerequisite events:** interaction.routed
- **Caveats:** Declined AgentWork records persist; a NEW AgentWork is created for the reroute attempt.

### interaction.expired
- **Recorded in:** `AgentWork.Status = 'Timeout'` (and DeclineDateTime is null)
- **Trigger:** Push Time-Out on the Routing Configuration elapses without agent action.
- **Prerequisite events:** interaction.routed
- **Caveats:** Configure Push Time-Out to a value larger than typical agent reaction time or you'll see spurious timeouts.

### interaction.talk.start
- **Recorded in:** For voice: `VoiceCall.CallStartDateTime`. For chat/messaging: `AgentWork.AcceptDateTime` (used as proxy). For Case: not directly modeled (Case has no talk/hold concept).
- **Trigger:** Voice line connects OR chat/messaging session begins.
- **Prerequisite events:** interaction.accepted
- **Caveats:** Voice channel introduces its own timing which can lag AgentWork acceptance by 1–3 seconds. See Known traps.

### interaction.talk.end
- **Recorded in:** For voice: `VoiceCall.CallEndDateTime`. For chat/messaging: `AgentWork.EndDateTime`.
- **Trigger:** Line disconnects / chat session ends.
- **Prerequisite events:** interaction.talk.start
- **Caveats:** ACW immediately follows talk.end — the CloseDateTime is later.

### interaction.acw.start
- **Recorded in:** Implicit — the window between `AgentWork.EndDateTime` and `AgentWork.CloseDateTime` (if the Presence Configuration includes ACW).
- **Trigger:** Talk ends and Presence Configuration says the agent goes into a Wrap-Up state.
- **Prerequisite events:** interaction.talk.end
- **Caveats:** If the Presence Configuration doesn't have a wrap-up state configured, ACW is zero-length.

### interaction.acw.end
- **Recorded in:** `AgentWork.CloseDateTime`
- **Trigger:** Agent clicks Close on the Omni-Channel widget after wrap-up.
- **Prerequisite events:** interaction.acw.start
- **Caveats:** Auto-close after N seconds is configurable; without auto-close, agents can leave records open indefinitely.

### interaction.transferred
- **Recorded in:** New `AgentWork` record on the receiving side; original AgentWork.Status = 'Transferred' or similar.
- **Trigger:** Agent uses "Transfer to Queue" or "Transfer to Agent" in the Omni-Channel widget.
- **Prerequisite events:** interaction.accepted
- **Caveats:** Warm transfer creates a `interaction.consulted` first; cold does not. Salesforce doesn't distinguish warm/cold/blind cleanly at the AgentWork level; check `TransferReason` and correlate.

### interaction.abandoned
- **Recorded in:** `PendingServiceRouting.Status = 'Abandoned'` before it's deleted; captured in AgentWork if the customer disconnects post-routing but pre-accept.
- **Trigger:** Customer disconnects / closes chat before an agent accepts.
- **Prerequisite events:** interaction.received
- **Caveats:** PSR deletion timing makes this brittle to observe — see Known traps.

### interaction.completed
- **Recorded in:** `AgentWork.Status = 'Closed'` + `CloseDateTime` populated
- **Trigger:** All wrap-up complete; agent has closed the work item.
- **Prerequisite events:** interaction.acw.end
- **Caveats:** Auto-close may fire the Closed status without the agent explicitly clicking Close.

### agent.login
- **Recorded in:** `UserServicePresence` (new row created with a StatusId whose StatusOption is not Offline)
- **Trigger:** Agent sets a non-Offline presence status via the Omni-Channel widget.
- **Prerequisite events:** none
- **Caveats:** Presence isn't the same as Salesforce user login — a user can be logged into Salesforce but Offline in Omni-Channel. Discovery must use UserServicePresence, not User.LastLoginDate.

### agent.logout
- **Recorded in:** `UserServicePresence` (new row with an Offline-category StatusId, or the previous row's EndDate)
- **Trigger:** Agent sets Offline presence, closes the browser, or session ends.
- **Prerequisite events:** agent.login
- **Caveats:** Browser close doesn't always emit a clean logout; UserServicePresence may show an open "Online" row indefinitely. Discovery should treat any UserServicePresence older than 24h with no EndDate as effectively logged out.

### agent.presence.change
- **Recorded in:** `UserServicePresence` (new row per transition)
- **Trigger:** Agent selects a different Presence Status in the Omni-Channel widget.
- **Prerequisite events:** agent.login
- **Caveats:** Auto-away transitions (from a Presence Configuration's inactivity timer) show up as system-initiated changes. Attribute mapping: `from_state` = previous row's StatusId → ServicePresenceStatus.StatusOption; `to_state` = current row's.

# Validation

1. **Setup verification.** In Setup, confirm Omni-Channel Settings shows enabled; at least one Service Channel, Presence Config, Presence Status, Queue, and Routing Config exist.
2. **Agent-side verification.** Log in as a User with the Presence Configuration assigned. Confirm the Omni-Channel widget appears in the utility bar. Set presence to Available. The widget should show your accepted-status and 0 active work items.
3. **End-to-end test.**
   - Have a second user (admin) create a Case and set its Owner to the Queue you configured.
   - Within ~2 seconds, expect an `AgentWork` record where UserId = your test agent's ID. SOQL: `SELECT Id, UserId, Status, AcceptDateTime FROM AgentWork ORDER BY CreatedDate DESC LIMIT 1`.
   - Click Accept in the Omni-Channel widget. Re-query — expect `AcceptDateTime` populated.
   - Click Close (or wait for auto-close). Re-query — expect `EndDateTime` and `CloseDateTime` populated.
4. **Presence verification.** SOQL: `SELECT Id, UserId, ServicePresenceStatusId, ConfiguredStatusId, StatusStartDate, StatusEndDate FROM UserServicePresence WHERE UserId = <agent Id> ORDER BY StatusStartDate DESC LIMIT 5`. Expect a row per presence change during the test.

# Known traps

- **AgentWork.AcceptDateTime ≠ voice line-connect time.** Voice channel records its own connect time in `VoiceCall.CallStartDateTime`. Use that if you need accurate talk-time for voice; using AcceptDateTime gives you Omni-Channel acceptance time which precedes actual talk by 1–3 seconds.
- **PendingServiceRouting rows are deleted after routing.** PSR is a working row Omni-Channel uses to track "not-yet-routed". Once routed, it's deleted. To capture `interaction.received` reliably, either (a) enable Field History Tracking on PSR, (b) run discovery frequently against PSR (which risks missing events), or (c) reconstruct from AgentWork.CreatedDate (which is `interaction.routed`, not received — off by the routing latency).
- **Omni-Channel doesn't record hold as a first-class concept.** Hold events live inside the underlying channel: `VoiceCall` transcript events or `Chat_Transcript` events. If hold time matters, layer the voice- or chat-specific blueprint on top of this one. That's why `interaction.hold.*` events are NOT in this blueprint's produces_events.
- **Queue members can be nested Public Groups.** GroupMember.UserOrGroupId can point at a Public Group which itself has GroupMembers. Walking the tree requires recursive expansion; naïve queries miss half the eligible agents.
- **Presence auto-away timers cause spurious declines.** The Presence Configuration has an idle timeout — if an agent doesn't accept within N seconds, they auto-set to Away and their AgentWork.DeclineDateTime is populated as if they'd declined. Configure the timeout explicitly to a value higher than realistic agent reaction time (60+ seconds typical) or accept that DeclineDateTime is a noisy signal.
- **UserServicePresence "still open" rows.** When an agent closes their browser without clicking Offline, the row's EndDate stays null indefinitely. Treat any presence row older than 24 hours with no EndDate as effectively closed.
````

- [ ] **Step 2: Verify the file was created and roughly the right size.**

```bash
wc -l "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon/ontology/blueprints/salesforce/queue_based.md"
```

Expected: at least 200 lines.

- [ ] **Step 3: Verify the framework can parse and validate it via the CLI.**

```bash
cd "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon"
PYTHONPATH=src python -m lexicon.blueprints validate 2>&1 | tail -20
```

Expected: `✓ .../salesforce/queue_based.md` (possibly with informational warnings, no errors). If errors appear, fix the blueprint content (never the validator) until errors clear.

- [ ] **Step 4: Confirm full test suite still passes.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 219 pass (no regressions; blueprint isn't yet consumed by any test).

- [ ] **Step 5: Commit.**

```bash
git add ontology/blueprints/salesforce/queue_based.md
git commit -m "feat(blueprints): author Salesforce queue_based reference blueprint"
```

---

## Task 13: Authoring guide (`ontology/blueprints/README.md`)

**Files:**
- Create: `ontology/blueprints/README.md`

Short authoring guide so future blueprint authors know how to write one.

- [ ] **Step 1: Create the file.** Write `ontology/blueprints/README.md`:

```markdown
# Flow Blueprints — authoring guide

A **Flow Blueprint** is a Markdown document that tells an admin how to configure a specific CRM/CCaaS platform for a specific routing model so it emits ACD-equivalent events. One file per (platform × routing_model) combination.

See `docs/superpowers/specs/2026-08-09-flow-blueprint-design.md` for the full design.

## Files in this directory

- `schema.yaml` — the closed vocabulary all blueprints validate against.
- `events.yaml` — the canonical ACD event taxonomy.
- `<platform>/<routing_model>.md` — one blueprint per combination.

## How to author a new blueprint

1. **Copy `salesforce/queue_based.md`** as a starting template.
2. **Set the frontmatter.**
   - `platform` — must be in `schema.yaml`'s `platforms` list. Add your platform to `schema.yaml` first if it's new (one-line PR).
   - `routing_model` — one of `queue_based | skill_based | presence_aware | overflow_escalation`.
   - `channels` — subset of `voice | chat | messaging | email | case`.
   - `produces_events` — the list of canonical events this configuration produces. Every one MUST appear in `events.yaml`; every one MUST have a matching `### <event>` subsection in section 5.
3. **Fill in the 7 sections** using the CRM-neutral headers exactly:
   - `# Overview` — 1–3 paragraphs. When to use / when not to.
   - `# Prerequisites` — bulleted list.
   - `# Configuration steps` — numbered click-path.
   - `# Object footprint` — Markdown table with the fixed 4 columns (Concept | Platform object.field | Populated when | Notes). Concept values must come from `schema.yaml`'s `concept_vocabulary`.
   - `# ACD event mapping` — one `### <event>` subsection per produces_events entry, with the fixed micro-fields (Recorded in / Trigger / Prerequisite events / Caveats).
   - `# Validation` — how the admin proves the setup works.
   - `# Known traps` (optional but recommended) — platform-specific gotchas.
4. **Validate:** `python -m lexicon.blueprints validate ontology/blueprints/<your_platform>/<your_routing_model>.md`
5. **Get a platform-savvy reviewer to sign off.** The framework can't verify that your Configuration steps actually work end-to-end.

## Adding a new platform

Edit `schema.yaml`, append the platform slug to `platforms`. That's the whole framework change. Then author `<new_platform>/<routing_model>.md`.

## Adding a new canonical concept

Edit `schema.yaml`, append to `concept_vocabulary`. All existing blueprints continue to validate — the vocabulary is additive.

## Adding a new event to the taxonomy

Edit `events.yaml`. New events default to `optional: true` so existing blueprints continue to validate. If you need it to be `optional: false`, you must also add it to every existing blueprint's produces_events + add matching `### <event>` subsections.

## Freshness

- `last_verified` older than 6 months → validator warns.
- `last_verified` older than 12 months → validator errors.

Bump `last_verified` when you re-verify against a new platform release.
```

- [ ] **Step 2: Confirm no test regressions** (the README isn't validated, but the CLI's `list` shouldn't be confused by it).

```bash
pytest -q 2>&1 | tail -3
```

Expected: 219 pass.

- [ ] **Step 3: Commit.**

```bash
git add ontology/blueprints/README.md
git commit -m "docs(blueprints): add authoring guide"
```

---

## Task 14: E2E integration test + CRM-neutrality grep gate

**Files:**
- Create: `tests/lexicon/blueprints/test_reference_blueprint_validates.py`
- Create: `tests/lexicon/blueprints/test_crm_neutrality.py`

Two load-bearing tests: the real Salesforce blueprint must validate, and no framework code names any specific CRM.

- [ ] **Step 1: Create `tests/lexicon/blueprints/test_reference_blueprint_validates.py`:**

```python
"""Load-bearing regression test — the committed Salesforce reference blueprint
must validate cleanly (warnings allowed, no errors).

Any framework change or blueprint change must keep this green.
"""
from pathlib import Path

from lexicon.blueprints.events import load_events, validate_taxonomy
from lexicon.blueprints.parser import parse_blueprint
from lexicon.blueprints.schema import load_schema
from lexicon.blueprints.validator import validate

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT_DIR = ROOT / "ontology" / "blueprints"


def test_events_taxonomy_is_valid():
    """events.yaml itself must have a valid DAG."""
    tax = load_events(BLUEPRINT_DIR / "events.yaml")
    errors = validate_taxonomy(tax)
    assert errors == [], f"events.yaml has taxonomy errors: {errors}"


def test_salesforce_queue_based_blueprint_validates_cleanly():
    """The reference blueprint must produce zero errors (warnings OK)."""
    schema = load_schema(BLUEPRINT_DIR / "schema.yaml")
    events = load_events(BLUEPRINT_DIR / "events.yaml")
    bp = parse_blueprint(BLUEPRINT_DIR / "salesforce" / "queue_based.md")
    errors = validate(bp, schema, events)
    hard_errors = [e for e in errors if e.severity == "error"]
    assert hard_errors == [], (
        "Salesforce reference blueprint has validation errors:\n" +
        "\n".join(f"  {e.section or ''}: {e.message}" for e in hard_errors)
    )


def test_cli_validate_exits_zero():
    """python -m lexicon.blueprints validate must exit 0 on the committed tree."""
    import subprocess
    import sys
    import os
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        [sys.executable, "-m", "lexicon.blueprints", "validate"],
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )
    assert r.returncode == 0, (
        f"validate CLI exited {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )
```

- [ ] **Step 2: Create `tests/lexicon/blueprints/test_crm_neutrality.py`:**

```python
"""CRM-neutrality gate — framework code must not name any specific CRM.

Spec §11 success criterion #6: `grep -r salesforce src/lexicon/blueprints/`
returns zero hits. Same for other platform names.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_DIR = ROOT / "src" / "lexicon" / "blueprints"

# Platform slugs from schema.yaml — these must NOT appear in framework code.
FORBIDDEN_TERMS = [
    "salesforce", "dynamics365", "servicenow_cx", "hubspot_service_hub",
    # Not-slug forms that would also indicate coupling:
    "AgentWork", "PendingServiceRouting", "UserServicePresence",
    "Omni-Channel", "Service Cloud",
]


def test_framework_code_does_not_reference_specific_crms():
    """Framework Python files must be platform-neutral."""
    py_files = [p for p in FRAMEWORK_DIR.rglob("*.py") if p.name != "__init__.py"]
    violations: list[tuple[Path, str, int]] = []
    for path in py_files:
        text = path.read_text()
        for term in FORBIDDEN_TERMS:
            # Case-insensitive match for slugs; case-sensitive for object names.
            if term.islower():
                pattern = re.compile(re.escape(term), re.IGNORECASE)
            else:
                pattern = re.compile(re.escape(term))
            for m in pattern.finditer(text):
                line_num = text.count("\n", 0, m.start()) + 1
                violations.append((path, term, line_num))
    assert violations == [], (
        "Framework code contains CRM-specific terms (violates CRM-neutrality):\n" +
        "\n".join(f"  {p}:{ln}  contains {t!r}" for p, t, ln in violations)
    )
```

- [ ] **Step 3: Run both tests to confirm they pass.**

```bash
pytest tests/lexicon/blueprints/test_reference_blueprint_validates.py tests/lexicon/blueprints/test_crm_neutrality.py -v
```

Expected: 4 pass.

If `test_salesforce_queue_based_blueprint_validates_cleanly` fails, fix the blueprint content (Task 12 file) — never weaken the test.

If `test_framework_code_does_not_reference_specific_crms` fails, remove the CRM-specific terms from the framework Python files. They belong in blueprint files, not framework code.

- [ ] **Step 4: Confirm full suite green.**

```bash
pytest -q 2>&1 | tail -3
```

Expected: 219 + 4 = 223 pass.

- [ ] **Step 5: Time the CLI validate to confirm the < 1s success criterion.**

```bash
cd "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon"
time (PYTHONPATH=src python -m lexicon.blueprints validate > /dev/null)
```

Expected: `real` under 1 second.

- [ ] **Step 6: Commit.**

```bash
git add tests/lexicon/blueprints/test_reference_blueprint_validates.py tests/lexicon/blueprints/test_crm_neutrality.py
git commit -m "test(blueprints): E2E reference-blueprint validates + CRM-neutrality gate"
```

---

## Final verification

- [ ] Run the full test suite:

```bash
cd "/Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon 2026/Lexicon"
pytest -v 2>&1 | tail -5
```

Expected: 223 pass, 0 failed.

- [ ] Inspect the final commit list:

```bash
git log --oneline main..HEAD
```

Expected: ~14 commits, one per task.

- [ ] Verify the four success criteria from spec §11 mechanically:

| # | Criterion | How to check |
|---|---|---|
| 1 | Framework is complete and consistent | `pytest tests/lexicon/blueprints/test_events.py tests/lexicon/blueprints/test_reference_blueprint_validates.py -v` passes |
| 2 | Validator catches all documented failure modes | `pytest tests/lexicon/blueprints/test_validator_basics.py tests/lexicon/blueprints/test_validator_sections.py -v` — 11 rule tests pass |
| 3 | Salesforce reference blueprint validates cleanly | `PYTHONPATH=src python -m lexicon.blueprints validate` → exit 0, `✓` next to the Salesforce blueprint |
| 5 | validate runs in < 1 second | `time` measurement in Task 14 step 5 |
| 6 | CRM-neutrality enforced in code | `pytest tests/lexicon/blueprints/test_crm_neutrality.py -v` passes |
| 7 | No existing test regresses | `pytest -q` reports 223 pass (172 pre-existing + 51 new) |

Criterion #4 (reference blueprint is a real document that an admin can follow) is a human judgement criterion that cannot be automated — a Salesforce-savvy reviewer should read `ontology/blueprints/salesforce/queue_based.md` end-to-end and sign off.

---

## Follow-ups (not part of this plan)

Deferred to separate specs per the design's out-of-scope list:

- **B1** — Auth-aware / anti-bot fetcher.
- **B3** — Object footprint prediction that feeds sub-project A's discovery pipeline.
- **B4** — Flow-configured mapping to canonical WFM (uses the `projects_to_canonical_wfm` hooks in events.yaml).
- **B2.5** — LLM-assisted blueprint drafting from platform docs.
- **Additional blueprints** — Salesforce skill_based / presence_aware / overflow_escalation; Dynamics 365; ServiceNow CX; HubSpot Service Hub. Framework supports them; authoring is separate work.
- **Editor plugin / language server** for on-save validation as you author.
- **PDF/HTML rendering** — Markdown is the output format; pandoc or GitHub already handles this.
- **Admin UI for browsing / editing blueprints** — could be a Streamlit page like `src/ui/app.py`.
