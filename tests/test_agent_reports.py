"""
Agent-Queue and Agent-System reports (both vendors):
  * approved executable maps reproduce their goldens and are DTD-valid
  * the reference auto-mapper proposes them correctly by reusing learned patterns
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

DTD = etree.DTD(str(ROOT / "schema/HistPlugin.dtd"))

CASES = [
    ("avaya",   "agentqueue",  "ontology/mappings/avaya.agentqueue.map.yaml",   "fixtures/avaya_agentqueue_sample.csv",    "fixtures/golden/AQ_060225.0900.avaya.expected.xml"),
    ("avaya",   "agentsystem", "ontology/mappings/avaya.agentsystem.map.yaml",  "fixtures/avaya_agentsystem_sample.csv",   "fixtures/golden/AS_060225.0900.avaya.expected.xml"),
    ("genesys", "agentqueue",  "ontology/mappings/genesys.agentqueue.map.yaml", "fixtures/genesys_agentqueue_sample.json",  "fixtures/golden/AQ_060225.0900.genesys.expected.xml"),
    ("genesys", "agentsystem", "ontology/mappings/genesys.agentsystem.map.yaml","fixtures/genesys_agentsystem_sample.json", "fixtures/golden/AS_060225.0900.genesys.expected.xml"),
]


def _norm(el):
    return (el.tag, (el.text or "").strip(), [_norm(c) for c in el])


def test_approved_maps_reproduce_goldens_and_validate():
    for vendor, report, mp_path, inp, gold in CASES:
        mp = yaml.safe_load((ROOT / mp_path).read_text())
        rows, dt, per = engine.load_any(str(ROOT / inp))
        xml = engine.transform(mp, rows, dt, per)
        assert DTD.validate(etree.fromstring(xml.encode())), f"{vendor} {report} not DTD-valid"
        got = _norm(etree.fromstring(xml.encode()))
        want = _norm(etree.fromstring((ROOT / gold).read_text().encode()))
        assert got == want, f"{vendor} {report} does not match golden"


def test_reference_automap_proposes_agent_reports_correctly(tmp_path):
    # Avaya catalog carries both hsplit and hagent fields; reference reuse should
    # produce correct agent maps with zero fixes.
    catalog = yaml.safe_load((ROOT / "fixtures/vendor_catalogs/avaya_hsplit_fields.yaml").read_text())
    for report, inp, gold in [
        ("agentqueue",  "fixtures/avaya_agentqueue_sample.csv",  "fixtures/golden/AQ_060225.0900.avaya.expected.xml"),
        ("agentsystem", "fixtures/avaya_agentsystem_sample.csv", "fixtures/golden/AS_060225.0900.avaya.expected.xml"),
    ]:
        fields, proposals = automap.propose_reference(catalog, report)
        p = tmp_path / f"avaya.{report}.yaml"
        p.write_text(yaml.safe_dump({"meta": {"vendor": "Avaya", "report": report}, "fields": fields, "proposals": proposals}, sort_keys=False))
        fixes = verify_mapping.run(str(p), str(ROOT / inp), str(ROOT / gold))
        assert fixes == [], f"reference proposal for {report} should need no fixes, got {fixes}"
