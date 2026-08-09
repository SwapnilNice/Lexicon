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
