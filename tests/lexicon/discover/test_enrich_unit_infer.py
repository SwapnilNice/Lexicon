from lexicon.discover.enrich.unit_infer import infer_units
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def test_ms_suffix_wins():
    f = _f("tTalk_ms", "Talk time.")
    infer_units([f])
    assert f.unit == "duration_ms"
    assert f.unit_confidence >= 0.9


def test_seconds_from_description():
    f = _f("acdtime", "Talk time in seconds.")
    infer_units([f])
    assert f.unit == "duration_seconds"


def test_count_from_description():
    f = _f("nHandled", "Count of handled contacts.")
    infer_units([f])
    assert f.unit == "count"


def test_percent_from_name():
    f = _f("SvcLvlPct", "Service level.")
    infer_units([f])
    assert f.unit == "percentage"


def test_unknown_when_silent():
    f = _f("mystery", "Some field.")
    infer_units([f])
    assert f.unit == "unknown"
    assert f.unit_confidence == 0.0


def test_openapi_x_unit_surface():
    f = _f("tTalk", "Talk time. (format: int64) (unit: milliseconds) (type: integer)")
    infer_units([f])
    assert f.unit == "duration_ms"
    assert "x-unit" in f.unit_signals or any("unit" in s for s in f.unit_signals)
