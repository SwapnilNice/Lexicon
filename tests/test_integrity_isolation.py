"""
Regression fence for the "don't disturb" constraint.

Confirms the existing engine + transformers still produce byte-identical XML
against the golden files after the Integrity Layer is present in the tree.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "fixtures" / "golden"
FIXTURES = ROOT / "fixtures"


def _run_engine(mapping_name, csv_name):
    r = subprocess.run(
        [sys.executable, str(ROOT / "src" / "engine.py"),
         str(ROOT / "ontology" / "mappings" / mapping_name),
         str(FIXTURES / csv_name)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_avaya_queue_xml_bytes_unchanged():
    got = _run_engine("avaya.queue.map.yaml", "avaya_queue_sample.csv")
    expected = (GOLDEN / "Q_060225.0900.expected.xml").read_text()
    assert got == expected, "engine XML output has drifted — integrity layer must not touch this"


def test_avaya_agentqueue_xml_bytes_unchanged():
    got = _run_engine("avaya.agentqueue.map.yaml", "avaya_agentqueue_sample.csv")
    expected = (GOLDEN / "AQ_060225.0900.avaya.expected.xml").read_text()
    assert got == expected


def test_avaya_agentsystem_xml_bytes_unchanged():
    got = _run_engine("avaya.agentsystem.map.yaml", "avaya_agentsystem_sample.csv")
    expected = (GOLDEN / "AS_060225.0900.avaya.expected.xml").read_text()
    assert got == expected


def test_sensor_reports_clean_on_engine_output(tmp_path):
    got = _run_engine("avaya.queue.map.yaml", "avaya_queue_sample.csv")
    xml_path = tmp_path / "out.xml"
    xml_path.write_text(got)
    r = subprocess.run(
        [sys.executable, str(ROOT / "src" / "sensor.py"), str(xml_path)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, f"sensor drift on stock engine output: {r.stdout}\n{r.stderr}"
