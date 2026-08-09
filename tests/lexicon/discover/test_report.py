from pathlib import Path

from lexicon.discover.models import ProposedField
from lexicon.discover.report import write_coverage_report


def test_writes_markdown_report(tmp_path):
    proposals = {
        "QueueValue":  ProposedField("split",              0.98, "queue_key_like: split"),
        "HandleTime":  ProposedField("acdtime + holdtime", 0.88, "composed"),
        "HandledShort":ProposedField(None,                 0.0,  "no candidate", needs_review=True),
    }
    out = tmp_path / "avaya_cms.md"
    write_coverage_report(
        vendor_slug="avaya_cms", report="queue",
        proposals=proposals,
        sources=[{"url": "https://x", "status": "ok", "pages": 37}],
        traps=[{"field": "acdtime", "kind": "exclusion", "target": "hold_time"}],
        path=out,
    )
    text = out.read_text()
    assert "# Discovery report — avaya_cms" in text
    assert "acdtime + holdtime" in text
    assert "no candidate" in text
    assert "2/3" in text or "found: 2" in text.lower()
    assert "acdtime" in text and "exclusion" in text


def test_missing_field_flagged_in_next_actions(tmp_path):
    proposals = {
        "HandleTime": ProposedField(None, 0.0, "no candidate", needs_review=True),
    }
    out = tmp_path / "r.md"
    write_coverage_report("v", "queue", proposals, sources=[], traps=[], path=out)
    text = out.read_text()
    assert "HandleTime" in text
    assert "needs" in text.lower() or "missing" in text.lower()
