from lexicon.discover.extract.html_structured import extract_html_structured
from lexicon.discover.models import SourceDoc


def _doc(html: str) -> SourceDoc:
    return SourceDoc(id="d1", kind="html", url="https://x/p", title="p", content=html, text="")


def test_two_column_table():
    html = """
    <table>
      <tr><th>Field</th><th>Description</th></tr>
      <tr><td>acdtime</td><td>Talk time of ACD calls.</td></tr>
      <tr><td>acwtime</td><td>After-call work time.</td></tr>
    </table>
    """
    raws = extract_html_structured(_doc(html))
    names = {r.name for r in raws}
    assert names == {"acdtime", "acwtime"}
    acd = next(r for r in raws if r.name == "acdtime")
    assert "Talk time" in acd.description
    assert acd.extractor == "html_structured"
    assert acd.confidence_extraction >= 0.9


def test_definition_list():
    html = """
    <dl>
      <dt>tTalk</dt><dd>Talk time in milliseconds.</dd>
      <dt>tHold</dt><dd>Hold time in milliseconds.</dd>
    </dl>
    """
    raws = extract_html_structured(_doc(html))
    assert {r.name for r in raws} == {"tTalk", "tHold"}


def test_ignores_wide_tables():
    """A 5-column table isn't a field-description table; skip it."""
    html = """
    <table>
      <tr><th>a</th><th>b</th><th>c</th><th>d</th><th>e</th></tr>
      <tr><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td></tr>
    </table>
    """
    assert extract_html_structured(_doc(html)) == []


def test_provenance_populated():
    html = "<table><tr><th>Field</th><th>Desc</th></tr><tr><td>x</td><td>y</td></tr></table>"
    raws = extract_html_structured(_doc(html))
    assert raws[0].source.doc_id == "d1"
    assert raws[0].source.url == "https://x/p"
    assert "table" in raws[0].source.locator.lower()
