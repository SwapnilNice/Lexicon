"""Canonical layer wraps engine.compute_fields; must never emit vendor terms."""
import pathlib
import yaml
import pytest

from src.integrity import canonical

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_mapping(name):
    return yaml.safe_load((ROOT / "ontology" / "mappings" / name).read_text())


def test_queue_row_produces_canonical_fields_only():
    mp = _load_mapping("avaya.queue.map.yaml")
    row = {"split": "44", "acdcalls": 48, "acceptable": 40, "abncalls": 3, "slvlabns": 2,
           "acdtime": 2880, "holdtime": 240, "acwtime": 600, "anstime": 480, "contactsactive": 1}
    out = canonical.derive_row(mp, row)
    # canonical keys only — no vendor terms
    forbidden = {"acdtime", "holdtime", "acwtime", "split", "logid", "abncalls", "slvlabns"}
    assert forbidden.isdisjoint(out.keys()), f"vendor terms leaked: {set(out.keys()) & forbidden}"
    # HandleTime = acdtime + holdtime (glossary)
    assert out["HandleTime"] == 3120
    assert out["QueueValue"] == "44"


def test_derive_records_from_csv_file(tmp_path):
    csv_path = tmp_path / "queue.csv"
    csv_path.write_text(
        "INTERVAL_START,split,acdcalls,acceptable,abncalls,slvlabns,acdtime,holdtime,acwtime,anstime,contactsactive\n"
        "20250602T0900,44,48,40,3,2,2880,240,600,480,1\n"
        "20250602T0900,13,20,18,1,1,1500,100,300,260,0\n"
    )
    mp = _load_mapping("avaya.queue.map.yaml")
    recs = canonical.derive_from_csv(mp, csv_path)
    assert len(recs) == 2
    assert {r["interval"] for r in recs} == {"09:00"}
    assert {r["day"] for r in recs} == {"2025-06-02"}
    assert {r["QueueValue"] for r in recs} == {"44", "13"}


def test_missing_vendor_column_raises_clean_error(tmp_path):
    csv_path = tmp_path / "q.csv"
    csv_path.write_text("INTERVAL_START,split,acdcalls\n20250602T0900,44,48\n")
    mp = _load_mapping("avaya.queue.map.yaml")
    with pytest.raises(KeyError):
        canonical.derive_from_csv(mp, csv_path)
