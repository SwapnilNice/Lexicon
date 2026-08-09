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
    channels_val = fm.get("channels")
    if channels_val is not None and not isinstance(channels_val, list):
        errors.append(_err(
            bp.path, "frontmatter",
            f"channels must be a YAML list; got {type(channels_val).__name__} ({channels_val!r}). "
            f"Use `channels: [voice, chat]`, not `channels: voice`.",
        ))
        channels_val = []
    for ch in channels_val or []:
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
    produces_val = fm.get("produces_events")
    if produces_val is not None and not isinstance(produces_val, list):
        errors.append(_err(
            bp.path, "frontmatter",
            f"produces_events must be a YAML list; got {type(produces_val).__name__} ({produces_val!r}). "
            f"Use `produces_events: [interaction.received, ...]`.",
        ))
        produces_val = []
    for ev in produces_val or []:
        if ev not in events.events:
            errors.append(_err(
                bp.path, "frontmatter",
                f"produces_events contains {ev!r} which is not in events.yaml",
            ))

    # --- 4a. All non-optional events must appear in produces_events ---
    declared_events = set(produces_val or [])
    for ev_name, ev_def in events.events.items():
        if not ev_def.optional and ev_name not in declared_events:
            errors.append(_err(
                bp.path, "frontmatter",
                f"non-optional event {ev_name!r} must appear in produces_events",
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

    # --- 6. Required sections present, in order (no order check for v1 — just presence) ---
    section_names = [h for h, _ in bp.sections]
    for req in schema.required_sections:
        if req not in section_names:
            errors.append(_err(bp.path, req, f"missing required section {req!r}"))
    if "Known traps" not in section_names:
        errors.append(_warn(
            bp.path, "Known traps",
            "recommended section 'Known traps' is missing",
        ))

    # --- 7. produces_events ↔ event subsections one-to-one ---
    declared = set(produces_val or [])
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
        pe_value = fields.get("Prerequisite events")
        if pe_value:
            for token in _parse_prerequisite_events_value(pe_value):
                if token not in events.events:
                    errors.append(_err(
                        bp.path, f"### {ev}",
                        f"Prerequisite events references {token!r} which is not in events.yaml",
                    ))

    # --- 9. Object footprint table ---
    if "Object footprint" in [h for h, _ in bp.sections]:
        footprint_body = dict(bp.sections).get("Object footprint", "")
        errors.extend(_validate_object_footprint(bp.path, footprint_body, schema))

    return errors


def _parse_prerequisite_events_value(value: str) -> list[str]:
    """Parse a 'Prerequisite events:' value into event names.

    Supported forms:
      "none"                    → []
      "event.a"                 → ["event.a"]
      "event.a, event.b"        → ["event.a", "event.b"]
      "event.a and event.b"     → ["event.a", "event.b"]
    """
    stripped = value.strip()
    if not stripped or stripped.lower() == "none":
        return []
    # Split on commas or " and "
    parts = [p.strip() for p in stripped.replace(" and ", ",").split(",")]
    return [p for p in parts if p]


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

    # Data rows start after the separator line (lines[1]).
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
