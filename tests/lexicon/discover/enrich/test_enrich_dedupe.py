from lexicon.discover.enrich.dedupe import dedupe_raw_fields
from lexicon.discover.models import FieldSource, RawField


def _rf(name, desc, doc_id, url):
    return RawField(
        name=name, description=desc,
        source=FieldSource(doc_id=doc_id, url=url,
                           locator="", snippet=""),
        extractor="html_structured", confidence_extraction=0.9,
    )


def test_same_name_merges_sources():
    a = _rf("acdtime", "Talk time", "d1", "u1")
    b = _rf("acdtime", "Talk time (dup)", "d2", "u2")
    fields = dedupe_raw_fields([a, b])
    assert len(fields) == 1
    assert len(fields[0].sources) == 2
    # description prefers longer/more detailed one
    assert fields[0].description == "Talk time (dup)"


def test_case_insensitive_merge():
    a = _rf("ACDTIME", "Talk time.", "d1", "u1")
    b = _rf("acdtime", "Talk time in seconds.", "d2", "u2")
    fields = dedupe_raw_fields([a, b])
    assert len(fields) == 1
    # canonical name is the first-seen casing
    assert fields[0].name == "ACDTIME"
    # description prefers the longer/more detailed one
    assert "seconds" in fields[0].description


def test_different_names_stay_separate():
    a = _rf("acdtime", "a", "d1", "u1")
    b = _rf("holdtime", "b", "d1", "u1")
    assert len(dedupe_raw_fields([a, b])) == 2


def test_empty_input_returns_empty():
    assert dedupe_raw_fields([]) == []
