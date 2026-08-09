"""
Lexicon computational guide — contract tests for the Avaya -> NICE WFM Queue report.

These enforce MEANING, not just structure. They are the deterministic gate the
agent's output must pass. Run:  pytest -v
"""
import pathlib
import sys
import re
from lxml import etree

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import transform_queue as tq                      # noqa: E402
import transform_queue_baseline_BUGGY as bad      # noqa: E402

CSV = ROOT / "fixtures" / "avaya_queue_sample.csv"
GOLDEN = ROOT / "fixtures" / "golden" / "Q_060225.0900.expected.xml"
DTD = ROOT / "schema" / "HistPlugin.dtd"


def _rows():
    import csv
    with open(CSV, newline="") as f:
        return list(csv.DictReader(f))


def _tree(xml_str):
    return etree.fromstring(xml_str.encode())


def _norm(el):
    """(tag, text, children) normalized, whitespace-insensitive."""
    text = (el.text or "").strip()
    return (el.tag, text, [_norm(c) for c in el])


# ---- structural / DTD ----------------------------------------------------

def test_output_is_dtd_valid():
    dtd = etree.DTD(str(DTD))
    tree = _tree(tq.transform_csv(str(CSV)))
    assert dtd.validate(tree), dtd.error_log.filter_from_errors()


def test_output_matches_golden():
    got = _norm(_tree(tq.transform_csv(str(CSV))))
    want = _norm(_tree(GOLDEN.read_text()))
    assert got == want


# ---- semantic contracts (the whole point) --------------------------------

def test_handle_time_excludes_acw():
    """HandleTime must be talk+hold, NOT talk+hold+acw."""
    xml = tq.transform_csv(str(CSV))
    t = _tree(xml)
    # skill 5001: ACDTIME 2880 + ACDHOLDTIME 240 = 3120 ; +ACW(600) = 3720 (wrong)
    val = t.xpath("//QueueData[QueueValue='44']/HandleTime/duration/totalseconds/text()")[0]
    assert int(val) == 3120, "HandleTime should be talk+hold (3120)"
    assert int(val) != 3720, "HandleTime must NOT include ACW"


def test_worktime_is_acw_only():
    t = _tree(tq.transform_csv(str(CSV)))
    val = t.xpath("//QueueData[QueueValue='44']/WorkTime/duration/totalseconds/text()")[0]
    assert int(val) == 600


def test_no_svclvlpct_for_inbound_voice():
    xml = tq.transform_csv(str(CSV))
    assert "<SvcLvlPct>" not in xml, "WFM derives service level for voice; do not emit it"


def test_no_vendor_term_leak_in_output():
    xml = tq.transform_csv(str(CSV))
    # case-SENSITIVE: vendor columns are lowercase; canonical tags are PascalCase
    for token in ["acwtime", "acdtime", "abncalls", "anstime", "holdtime", "logid", "slvlabns"]:
        assert not re.search(rf"\b{token}\b", xml), f"Avaya term '{token}' leaked into output"


# ---- proof the harness actually catches the baseline ---------------------

def test_baseline_is_rejected():
    """The no-Lexicon baseline must FAIL these contracts (before/after proof)."""
    xml = bad.build_xml(_rows())
    t = _tree(xml)
    ht = int(t.xpath("//QueueData[QueueValue='44']/HandleTime/duration/totalseconds/text()")[0])
    leaked = bool(re.search(r"\bacwtime\b", xml))
    has_svc = "<SvcLvlPct>" in xml
    assert ht == 3720 and (leaked or has_svc), "baseline should contain the injected silent errors"
