from lexicon.discover.extract.markdown import extract_markdown
from lexicon.discover.models import SourceDoc


def _doc(md: str) -> SourceDoc:
    return SourceDoc(id="d1", kind="markdown", url="https://x/p.md",
                     title="p", content=md, text="")


def test_extracts_h2_sections_with_api_id():
    md = """
# Top

## Abandonment rate
<a name="abandonment-rate"></a>

This metric measures the percentage of abandoned contacts.

**Metric type**: String
+ [GetMetricDataV2](https://x) API: `ABANDONMENT_RATE`

## Agents on call
<a name="agents-on-call"></a>

Number of agents currently on a call.

+ [GetMetricDataV2](https://x) API: `AGENTS_ON_CALL`
"""
    raws = extract_markdown(_doc(md))
    names = {r.name for r in raws}
    assert names == {"ABANDONMENT_RATE", "AGENTS_ON_CALL"}
    ab = next(r for r in raws if r.name == "ABANDONMENT_RATE")
    assert "Abandonment rate" in ab.description
    assert "abandoned contacts" in ab.description.lower()
    assert ab.extractor == "markdown"


def test_falls_back_to_heading_when_no_api_id():
    md = """
## Custom metric
Just a heading with a description, no API id in backticks.
"""
    raws = extract_markdown(_doc(md))
    assert len(raws) == 1
    assert raws[0].name == "Custom metric"


def test_skips_content_before_first_h2():
    md = """
Some intro paragraph.

Another intro paragraph.

## First metric
Description here. `FIRST_METRIC`
"""
    raws = extract_markdown(_doc(md))
    assert [r.name for r in raws] == ["FIRST_METRIC"]


def test_does_not_split_on_h3():
    md = """
## Parent metric
A description. `PARENT`

### Sub-heading
Not a top-level metric.
"""
    raws = extract_markdown(_doc(md))
    assert len(raws) == 1
    assert raws[0].name == "PARENT"


def test_ignores_non_markdown_kind():
    """The extractor is dispatch-safe: only handles kind='markdown'."""
    html_doc = SourceDoc(id="d1", kind="html", url="https://x", title="x",
                         content="## Fake\n`FAKE`", text="")
    assert extract_markdown(html_doc) == []


def test_provenance_populated():
    md = "## Metric X\nDescription. `METRIC_X`\n"
    raws = extract_markdown(_doc(md))
    src = raws[0].source
    assert src.doc_id == "d1"
    assert src.url == "https://x/p.md"
    assert src.locator == "## Metric X"
