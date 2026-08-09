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
