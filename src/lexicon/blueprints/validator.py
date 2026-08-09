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
