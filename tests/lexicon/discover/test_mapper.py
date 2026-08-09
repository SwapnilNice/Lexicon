"""Tests for src/lexicon/discover/mapper.py (Task 18).

All tests are flat (no classes).  They drive propose_mapping() with
hand-crafted EnrichedField lists that mirror real Avaya / Genesys fields
after the enrich pipeline has run.
"""
from lexicon.discover.enrich.semantic_tag import tag_fields
from lexicon.discover.enrich.trap_detect import detect_traps
from lexicon.discover.enrich.unit_infer import infer_units
from lexicon.discover.mapper import propose_mapping
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def _enrich(fields):
    infer_units(fields)
    tag_fields(fields)
    detect_traps(fields)
    return fields


def test_avaya_handle_time_composed_from_talk_and_hold():
    fields = _enrich([
        _f("acdtime", "Talk time of ACD calls. Does NOT include holdtime."),
        _f("holdtime", "Hold time on ACD calls, in seconds."),
    ])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HandleTime"]
    assert ht.formula == "acdtime + holdtime"
    assert 0.5 <= ht.confidence <= 0.95   # composition of two structural sources


def test_leaf_field_pick_hold_time():
    fields = _enrich([_f("holdtime", "Hold time on ACD calls, in seconds.")])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HoldTime"]
    assert ht.formula == "holdtime"


def test_no_candidate_marks_needs_review():
    fields = _enrich([_f("holdtime", "Hold time on ACD calls, in seconds.")])
    proposed = propose_mapping(fields, report="queue")
    handle = proposed["HandleTime"]
    assert handle.formula is None
    assert handle.needs_review is True
    assert "missing" in handle.rationale.lower() or "no candidate" in handle.rationale.lower()


def test_forbid_tags_rejects_acw_leak():
    """Composition must NOT include an acw-tagged field even if unit matches."""
    fields = _enrich([
        _f("acdtime",  "Talk time of ACD calls. Does NOT include holdtime."),
        _f("holdtime", "Hold time on ACD calls, in seconds."),
        _f("acwtime",  "After call work time, in seconds."),
    ])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HandleTime"]
    assert "acwtime" not in (ht.formula or "")


def test_genesys_ms_unit_conversion_flagged():
    """When peer fields are ms, we surface that as a unit_slip trap; the mapper
    generates a `/ 1000` conversion in the formula for a duration_seconds target."""
    fields = _enrich([
        _f("tTalk", "Talk time in milliseconds."),
        _f("tHeld", "Hold time in milliseconds."),
        _f("tAcw",  "ACW time in milliseconds."),
    ])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HandleTime"]
    # HandleTime is duration_seconds; sources are ms — conversion required
    assert "/ 1000" in (ht.formula or "")
    # confidence should still be reasonable (composition of structural fields)
    assert ht.confidence >= 0.3


def test_llm_only_cap_at_0_85():
    """A field with only LLM-tagged confidence (no structural signal) must
    cap below 0.85 even if enrichment gave high weights."""
    # This test verifies the confidence rubric formula in isolation.
    from lexicon.discover.mapper import _cap_confidence
    assert _cap_confidence(0.99, has_structural=False) <= 0.85
    assert _cap_confidence(0.99, has_structural=True) == 0.99
