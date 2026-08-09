"""
Lexicon contract tests for the Genesys -> NICE WFM Queue report.
Same canonical contracts as Avaya, plus the two Genesys-specific traps:
milliseconds->seconds, and HandleTime must EXCLUDE ACW (tHandle includes it).
"""
import pathlib
import sys
import re
from lxml import etree

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import transform_queue_genesys as tg   # noqa: E402

JSON = ROOT / "fixtures" / "genesys_queue_sample.json"
GOLDEN = ROOT / "fixtures" / "golden" / "Q_060225.0900.genesys.expected.xml"
DTD = ROOT / "schema" / "HistPlugin.dtd"


def _tree(xml_str):
    return etree.fromstring(xml_str.encode())


def _norm(el):
    return (el.tag, (el.text or "").strip(), [_norm(c) for c in el])


def test_output_is_dtd_valid():
    dtd = etree.DTD(str(DTD))
    assert dtd.validate(_tree(tg.transform_json(str(JSON)))), dtd.error_log.filter_from_errors()


def test_output_matches_golden():
    got = _norm(_tree(tg.transform_json(str(JSON))))
    want = _norm(_tree(GOLDEN.read_text()))
    assert got == want


def test_handle_time_excludes_acw_and_is_seconds():
    """Sales: tTalk 3000s + tHeld 300s = 3300 (NOT tHandle 4000, NOT ms)."""
    t = _tree(tg.transform_json(str(JSON)))
    val = int(t.xpath("//QueueData[QueueValue='Sales']/HandleTime/duration/totalseconds/text()")[0])
    assert val == 3300, "HandleTime must be (tTalk+tHeld)/1000"
    assert val != 4000, "must NOT use tHandle (it includes ACW)"
    assert val != 3300000, "must be seconds, not milliseconds"


def test_worktime_is_acw_seconds():
    t = _tree(tg.transform_json(str(JSON)))
    assert int(t.xpath("//QueueData[QueueValue='Sales']/WorkTime/duration/totalseconds/text()")[0]) == 700


def test_durations_are_seconds_not_ms():
    """No duration should look like a raw ms value (all our seconds are < 100000)."""
    t = _tree(tg.transform_json(str(JSON)))
    for v in t.xpath("//totalseconds/text()"):
        assert int(v) < 100000, f"suspicious duration {v} — looks like milliseconds"


def test_no_vendor_term_leak():
    xml = tg.transform_json(str(JSON))
    for token in ["tHandle", "tTalk", "tHeld", "tAcw", "_ms", "queueId"]:
        assert token not in xml, f"Genesys term '{token}' leaked into output"
