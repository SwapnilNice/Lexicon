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
