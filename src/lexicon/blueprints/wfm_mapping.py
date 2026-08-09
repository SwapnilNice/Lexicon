"""Derive a canonical WFM mapping proposal from a Flow Blueprint.

This is a v1 slice of sub-project B4 (flow-configured mapping). It reads a
blueprint's ACD event mapping section, pulls the `**Recorded in:**` value
for each event, and — using the `projects_to_canonical_wfm` hooks in
events.yaml plus the compositional derivations in canonical_wfm.yaml —
emits a mapping proposal keyed on canonical WFM fields.

The output is a REFERENCE document (not a directly-executable formula for
engine.py, because CRM-style timestamp subtraction requires integration
code the caller must write). Shape mirrors the sub-project A
`PROPOSED.yaml` so the same review workflow applies: the human ratifies
the formula, then implements it in their platform → NICE WFM integration.

Non-goals (deferred to full B4 later):
- Aggregation / counting formulas (HandledShort, AbandonedLong, etc.) —
  these need query-style GROUP BY which is out of scope for a v1 slice.
- Executable evaluation. This module outputs proposals only.
"""
from __future__ import annotations
from pathlib import Path
import re

import yaml

from .parser import parse_blueprint


# Match a platform-style `Object.Field` token inside backticks (e.g. a CRM
# object's timestamp column). Format: identifier starting with an upper-case
# letter, dot separator, one or more sub-identifiers.
_OBJECT_FIELD_RE = re.compile(r"`([A-Z][A-Za-z0-9_]{1,60}(?:\.[A-Za-z][A-Za-z0-9_]{0,60})+)`")


def _first_object_field(text: str) -> str | None:
    """From a `Recorded in:` value, return the first backticked Object.Field token.

    Blueprint values often list multiple channels (e.g. "For voice: `<VoiceObj>.<CallStart>`.
    For chat: `<InteractionObj>.<AcceptTime>` ..."). We take the first match — the human
    reviewer can broaden it based on their target channel."""
    m = _OBJECT_FIELD_RE.search(text)
    return m.group(1) if m else None


def _load_events_projections(events_path: Path) -> dict[str, str]:
    """Return {event_name: canonical_wfm_concept} for events that have a `projects_to_canonical_wfm` hook."""
    raw = yaml.safe_load(events_path.read_text()) or {}
    out: dict[str, str] = {}
    for name, spec in (raw.get("events") or {}).items():
        target = (spec or {}).get("projects_to_canonical_wfm")
        if target:
            out[name] = target
    return out


def _load_canonical_derivations(canon_path: Path, section: str = "queue") -> dict[str, dict]:
    """Return {canonical_field: derivation_spec} for compositional canonical fields.

    e.g. queue.HandleTime has derivation {formula: "{talk} + {hold}", components: [...]}"""
    raw = yaml.safe_load(canon_path.read_text()) or {}
    out: dict[str, dict] = {}
    for field_name, spec in (raw.get(section) or {}).items():
        if isinstance(spec, dict) and "derivation" in spec:
            out[field_name] = spec["derivation"]
    return out


def derive_wfm_mapping(
    blueprint_path: Path,
    events_path: Path,
    canonical_path: Path,
    report: str = "queue",
) -> dict:
    """Return a mapping proposal in the shape of ontology/proposed/*.PROPOSED.yaml.

    The `fields` dict maps canonical field names to a reference formula
    (e.g. `<InteractionObj>.<EndTime> - <InteractionObj>.<AcceptTime>`). The
    `proposals` dict adds confidence + rationale per field, matching
    verify_mapping.py's expected input shape.
    """
    bp = parse_blueprint(blueprint_path)
    projections = _load_events_projections(events_path)   # event → wfm_concept
    derivations = _load_canonical_derivations(canonical_path, section=report_section(report))

    # Step 1: extract primitive WFM concepts (talk_time, hold_time, acw_time)
    # by pairing .start/.end events that both project to the same concept.
    concept_formulas: dict[str, str] = {}
    concept_provenance: dict[str, list[str]] = {}
    concept_rationale: dict[str, str] = {}

    for event_name, subsection in bp.event_subsections.items():
        target_concept = projections.get(event_name)
        if not target_concept:
            continue
        recorded_in = subsection.get("Recorded in", "")
        start_ref = _first_object_field(recorded_in)
        if start_ref is None:
            continue
        # Find the paired ".end" event with the same target concept (or the same base name + ".end")
        base = event_name.rsplit(".", 1)[0]                 # e.g. interaction.talk
        end_name = f"{base}.end"
        end_sub = bp.event_subsections.get(end_name, {})
        end_ref = _first_object_field(end_sub.get("Recorded in", "")) if end_sub else None
        if end_ref is None:
            # No paired .end — record the start as the value alone (customer may aggregate).
            concept_formulas[target_concept] = start_ref
            concept_provenance[target_concept] = [event_name]
            concept_rationale[target_concept] = f"single-event value from `{event_name}` (no paired .end in blueprint)"
        else:
            concept_formulas[target_concept] = f"{end_ref} - {start_ref}"
            concept_provenance[target_concept] = [event_name, end_name]
            concept_rationale[target_concept] = f"duration between `{event_name}` and `{end_name}` (in seconds)"

    # Step 2: for each canonical WFM field with a derivation, compose from primitives.
    fields: dict[str, str | None] = {}
    proposals: dict[str, dict] = {}

    for canon_field, deriv in derivations.items():
        components = deriv.get("components") or []
        placeholders: dict[str, str] = {}
        missing: list[str] = []
        for c in components:
            tag = c.get("tag", "").removesuffix("_like")       # talk_time_like → talk_time
            placeholder = c.get("placeholder")
            if placeholder is None:
                continue
            if tag in concept_formulas:
                placeholders[placeholder] = f"({concept_formulas[tag]})"
            elif c.get("required", True):
                missing.append(tag)

        if missing:
            fields[canon_field] = None
            proposals[canon_field] = {
                "proposed": None,
                "confidence": 0.0,
                "rationale": f"blueprint doesn't produce events for: {missing}",
                "needs_review": True,
            }
        else:
            formula = deriv["formula"].format(**placeholders)
            fields[canon_field] = formula
            proposals[canon_field] = {
                "proposed": formula,
                "confidence": 0.75,
                "rationale": (
                    f"composed via canonical derivation from "
                    f"{sorted(placeholders.keys())}; source events documented in blueprint"
                ),
                "needs_review": True,
            }

    # Step 3: direct primitives that don't need composition (WorkTime = acw_time, HoldTime = hold_time,
    # QueueDelayTime = queue_delay_time). Only emit if they weren't already handled by a derivation
    # above (some canonical fields may be both leaf AND composed in the ontology).
    LEAF_TO_CONCEPT = {
        "HoldTime": "hold_time",
        "WorkTime": "acw_time",
        "QueueDelayTime": "queue_delay_time",
    }
    for canon_field, concept in LEAF_TO_CONCEPT.items():
        if canon_field in fields:
            continue
        if concept in concept_formulas:
            fields[canon_field] = concept_formulas[concept]
            proposals[canon_field] = {
                "proposed": concept_formulas[concept],
                "confidence": 0.80,
                "rationale": concept_rationale.get(concept, "leaf projection"),
                "needs_review": True,
            }
        else:
            fields[canon_field] = None
            proposals[canon_field] = {
                "proposed": None,
                "confidence": 0.0,
                "rationale": f"blueprint doesn't produce events that project to {concept}",
                "needs_review": True,
            }

    return {
        "meta": {
            "vendor": bp.frontmatter.get("platform"),
            "vendor_display_name": bp.frontmatter.get("platform_display_name"),
            "report": report,
            "status": "proposed",
            "produced_by": "lexicon.blueprints.wfm_mapping",
            "produced_from_blueprint": str(blueprint_path.name),
            "routing_model": bp.frontmatter.get("routing_model"),
            "note": (
                "This mapping was DERIVED from the blueprint's ACD event mapping. "
                "Formulas reference platform-specific object.field tokens as they appear "
                "in the blueprint; the customer's integration must implement the arithmetic "
                "(timestamp diffs → seconds, aggregations) before feeding the values to engine.py."
            ),
        },
        # Primitive concepts extracted from the blueprint. Even when full
        # canonical composition (HandleTime = talk + hold) fails because a
        # component isn't produced, the primitives are individually useful.
        "primitives": {
            concept: {
                "formula": formula,
                "source_events": concept_provenance.get(concept, []),
                "rationale": concept_rationale.get(concept, ""),
            }
            for concept, formula in concept_formulas.items()
        },
        "fields": {k: v for k, v in fields.items() if v is not None},
        "proposals": proposals,
    }


def report_section(report: str) -> str:
    """Report name → canonical_wfm.yaml section name."""
    return {"queue": "queue", "agentqueue": "agent_queue", "agentsystem": "agent_system"}[report]
