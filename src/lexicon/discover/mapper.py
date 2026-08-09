"""Propose a canonical mapping from enriched fields + canonical ontology.

Output shape mirrors today's ontology/proposed/<vendor>.<report>.PROPOSED.yaml
so verify_mapping.py / engine.py consume it unchanged.

Algorithm (per canonical concept C in the current report):
  1. Shortlist fields whose semantic_tags overlap with C's expected tag family
     (or, for composed concepts, each component's tag family).
  2. Unit-filter: drop candidates whose unit != C.unit, unless a unit_slip trap
     lets us insert a conversion (ms -> s).
  3. Rank by weight * unit_confidence.
  4. If C has a derivation block, fill each placeholder from the shortlist and
     compose the formula. Reject candidates whose tags appear in forbid_tags.
  5. Confidence: min(component confidences), capped per rubric.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml

from .models import EnrichedField, ProposedField


ROOT = Path(__file__).resolve().parents[3]
CANON = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())


REPORT_SECTION = {
    "queue": "queue",
    "agentqueue": "agent_queue",
    "agentsystem": "agent_system",
}

# Which tag family we expect for each simple (non-composed) canonical field.
LEAF_TAG_MAP: dict[str, str] = {
    "HoldTime": "hold_time_like",
    "WorkTime": "acw_time_like",
    "QueueDelayTime": "queue_delay_time_like",
    "ReadyTime": "ready_time_like",
    "NotReadyTime": "not_ready_time_like",
    "LoginTime": "login_time_like",
    "InternalHandleTime": "internal_time_like",
    "OutboundHandleTime": "outbound_time_like",
    "Handled": "handled_total_like",
    "HandledShort": "handled_within_sl_like",
    "HandledLong": "handled_total_like",   # arithmetic handled below
    "AbandonedShort": "abandoned_within_sl_like",
    "AbandonedLong": "abandoned_total_like",  # arithmetic below
    "ContactsActive": "contacts_active_like",
    "InternalContacts": "internal_count_like",
    "OutboundContacts": "outbound_count_like",
    "QueueValue": "queue_key_like",
    "AgentValue": "agent_key_like",
}

# Which canonical fields need "total - within_sl" arithmetic
LONG_DIFF: dict[str, tuple[str, str]] = {
    "HandledLong":   ("handled_total_like", "handled_within_sl_like"),
    "AbandonedLong": ("abandoned_total_like", "abandoned_within_sl_like"),
}


def _canonical_fields_for_report(report: str) -> list[str]:
    section = REPORT_SECTION[report]
    fields = []
    for name, spec in (CANON[section] or {}).items():
        media = (spec.get("media") or {}).get("immediate_response", "not_required")
        # Include only fields we need for the immediate_response media scope,
        # matching src/automap.py's target_fields().
        if report != "queue" or media in ("required", "required_if_available"):
            fields.append(name)
    return fields


def _weight_for_tag(field: EnrichedField, tag: str) -> float:
    for t in field.semantic_tags:
        if t.tag == tag:
            return t.weight
    return 0.0


def _pick_best(
    fields: list[EnrichedField],
    tag: str,
    target_unit: str,
    forbid_tags: set[str] = frozenset(),
) -> tuple[EnrichedField | None, float]:
    best, best_score = None, 0.0
    for f in fields:
        if any(t.tag in forbid_tags for t in f.semantic_tags):
            continue
        w = _weight_for_tag(f, tag)
        if w < 0.4:
            continue
        unit_ok = (
            f.unit == target_unit
            or (target_unit == "duration_seconds" and f.unit == "duration_ms")
            or target_unit == "key"                        # keys are always OK
        )
        if not unit_ok:
            continue
        score = w * (f.unit_confidence or 0.5)
        if score > best_score:
            best, best_score = f, score
    return best, best_score


def _operand(field: EnrichedField, target_unit: str) -> str:
    if target_unit == "duration_seconds" and field.unit == "duration_ms":
        return f"{field.name} / 1000"
    return field.name


def _cap_confidence(raw: float, has_structural: bool) -> float:
    if has_structural:
        return min(raw, 1.0)
    return min(raw, 0.85)


def _propose_composed(
    canon_field: dict,
    canon_unit: str,
    fields: list[EnrichedField],
) -> ProposedField:
    d = canon_field["derivation"]
    forbid = set(d.get("forbid_tags") or [])
    placeholders: dict[str, str] = {}
    weights: list[float] = []
    picked_names: list[str] = []
    missing = []
    for comp in d["components"]:
        f, s = _pick_best(fields, comp["tag"], canon_unit, forbid_tags=forbid)
        if f is None:
            if comp.get("required", True):
                missing.append(comp["tag"])
            continue
        placeholders[comp["placeholder"]] = _operand(f, canon_unit)
        weights.append(s)
        picked_names.append(f.name)
    if missing:
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"missing components: {missing}",
            needs_review=True,
        )
    formula = d["formula"].format(**placeholders)
    has_structural = all(w > 0.0 for w in weights)
    conf = _cap_confidence(min(weights), has_structural=has_structural)
    return ProposedField(
        formula=formula,
        confidence=round(conf, 2),
        rationale=f"composed from {picked_names} per derivation",
        needs_review=conf < 0.6,
    )


def _propose_leaf(
    field_name: str,
    canon_unit: str,
    fields: list[EnrichedField],
) -> ProposedField:
    # LONG_DIFF fields: total - within_sl
    if field_name in LONG_DIFF:
        total_tag, sl_tag = LONG_DIFF[field_name]
        total, ts = _pick_best(fields, total_tag, canon_unit)
        sl,    ss = _pick_best(fields, sl_tag,    canon_unit)
        if total and sl:
            conf = _cap_confidence(min(ts, ss), has_structural=True)
            return ProposedField(
                formula=f"{_operand(total, canon_unit)} - {_operand(sl, canon_unit)}",
                confidence=round(conf, 2),
                rationale=f"{total.name} - {sl.name}",
                needs_review=conf < 0.6,
            )
        if total:
            return ProposedField(
                formula=_operand(total, canon_unit),
                confidence=round(_cap_confidence(ts * 0.6, True), 2),
                rationale=f"total-only fallback ({total.name}); within-SL split missing",
                needs_review=True,
            )
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"no candidate for {total_tag}",
            needs_review=True,
        )

    tag = LEAF_TAG_MAP.get(field_name)
    if not tag:
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"no tag mapping for canonical field {field_name}",
            needs_review=True,
        )
    best, score = _pick_best(fields, tag, canon_unit)
    if best is None:
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"no candidate matching {tag} with unit={canon_unit}",
            needs_review=True,
        )
    conf = _cap_confidence(score, has_structural=True)
    return ProposedField(
        formula=_operand(best, canon_unit),
        confidence=round(conf, 2),
        rationale=f"best {tag} match: {best.name} (weight={score:.2f})",
        needs_review=conf < 0.6,
    )


def propose_mapping(
    fields: list[EnrichedField],
    *,
    report: str = "queue",
) -> dict[str, ProposedField]:
    section = REPORT_SECTION[report]
    out: dict[str, ProposedField] = {}
    for cf in _canonical_fields_for_report(report):
        spec = (CANON[section] or {}).get(cf, {})
        unit = spec.get("unit", "count")
        if "derivation" in spec:
            out[cf] = _propose_composed(spec, unit, fields)
        else:
            out[cf] = _propose_leaf(cf, unit, fields)
    return out
