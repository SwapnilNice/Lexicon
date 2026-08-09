"""
Tests for the AI-in-the-loop pieces: the executable engine, and the
propose -> verify loop (auto-mapper graded against the golden oracle).
"""
import pathlib
import sys
import yaml
from lxml import etree

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import engine            # noqa: E402
import automap           # noqa: E402
import verify_mapping    # noqa: E402


def _norm(el):
    return (el.tag, (el.text or "").strip(), [_norm(c) for c in el])


def _same(xml_str, golden_path):
    a = _norm(etree.fromstring(xml_str.encode()))
    b = _norm(etree.fromstring(pathlib.Path(golden_path).read_text().encode()))
    return a == b


# ---- the executable engine + APPROVED maps reproduce the goldens ----------

def test_engine_avaya_approved_matches_golden():
    mp = yaml.safe_load((ROOT / "ontology/mappings/avaya.queue.map.yaml").read_text())
    rows, dt, per = engine.load_csv(str(ROOT / "fixtures/avaya_queue_sample.csv"))
    xml = engine.transform(mp, rows, dt, per)
    assert _same(xml, ROOT / "fixtures/golden/Q_060225.0900.expected.xml")


def test_engine_genesys_approved_matches_golden():
    mp = yaml.safe_load((ROOT / "ontology/mappings/genesys.queue.map.yaml").read_text())
    rows, dt, per = engine.load_genesys(str(ROOT / "fixtures/genesys_queue_sample.json"))
    xml = engine.transform(mp, rows, dt, per)
    assert _same(xml, ROOT / "fixtures/golden/Q_060225.0900.genesys.expected.xml")


# ---- helper: run automap -> temp file ------------------------------------

def _propose(catalog_rel, vendor, tmp_path):
    catalog = yaml.safe_load((ROOT / catalog_rel).read_text())
    fields, proposals = automap.propose_heuristic(catalog)
    doc = {"meta": {"vendor": vendor, "report": "queue", "status": "proposed"},
           "fields": fields, "proposals": proposals}
    p = tmp_path / f"{vendor}.PROPOSED.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return str(p)


# ---- the harness catches the AI's residual errors ------------------------

def test_avaya_proposal_partially_correct_and_handle_time_caught(tmp_path):
    proposed = _propose("fixtures/vendor_catalogs/avaya_hsplit_fields.yaml", "Avaya", tmp_path)
    fixes = verify_mapping.run(proposed, str(ROOT / "fixtures/avaya_queue_sample.csv"),
                               str(ROOT / "fixtures/golden/Q_060225.0900.expected.xml"))
    # The simple 1:1 fields are correct; the composite/derived ones are caught.
    assert "HandleTime" in fixes, "the classic missing-hold error must be caught"
    assert "HandledShort" in fixes and "AbandonedShort" in fixes
    assert "QueueValue" not in fixes and "WorkTime" not in fixes
    assert 0 < len(fixes) < 10, "should be partial: some pass, some fail"


def test_genesys_proposal_units_and_tHandle_trap_caught(tmp_path):
    proposed = _propose("fixtures/vendor_catalogs/genesys_conversation_metrics.yaml", "Genesys", tmp_path)
    fixes = verify_mapping.run(proposed, str(ROOT / "fixtures/genesys_queue_sample.json"),
                               str(ROOT / "fixtures/golden/Q_060225.0900.genesys.expected.xml"))
    # tHandle (includes ACW) and the millisecond durations are all caught.
    assert "HandleTime" in fixes, "tHandle trap must be caught"
    assert "HoldTime" in fixes and "WorkTime" in fixes, "millisecond unit errors must be caught"
    assert "QueueValue" not in fixes
