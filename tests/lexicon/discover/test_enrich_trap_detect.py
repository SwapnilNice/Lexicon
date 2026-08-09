from lexicon.discover.enrich.trap_detect import detect_traps
from lexicon.discover.enrich.semantic_tag import tag_fields
from lexicon.discover.enrich.unit_infer import infer_units
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def test_exclusion_trap_on_acdtime():
    fields = [
        _f("acdtime", "Talk time of ACD calls. Does NOT include holdtime."),
        _f("holdtime", "Hold time of ACD calls."),
    ]
    tag_fields(fields)
    detect_traps(fields)
    acd = fields[0]
    traps = [t for t in acd.traps if t.kind == "exclusion"]
    assert traps
    assert traps[0].target == "hold_time"


def test_no_trap_when_no_signal():
    fields = [_f("acdtime", "Talk time of ACD calls.")]
    tag_fields(fields)
    detect_traps(fields)
    assert fields[0].traps == []


def test_unit_slip_trap():
    fields = [
        _f("tTalk", "Talk time in milliseconds."),
        _f("tHold", "Hold time in milliseconds."),
        _f("tAcw",  "ACW time in milliseconds."),
        _f("tWait", "Delay in milliseconds."),
    ]
    tag_fields(fields)
    infer_units(fields)
    # give one field seconds instead, to make it the odd-one-out
    fields[3].unit = "duration_seconds"
    detect_traps(fields)
    assert any(t.kind == "unit_slip" for t in fields[3].traps)


def test_inclusion_trap_on_thandle():
    fields = [
        _f("tHandle", "Total handle time. Includes wrap-up (ACW)."),
        _f("tAcw",    "ACW time in milliseconds."),
    ]
    tag_fields(fields)
    detect_traps(fields)
    inclusions = [t for t in fields[0].traps if t.kind == "inclusion"]
    assert inclusions
    assert inclusions[0].target == "acw_time"
