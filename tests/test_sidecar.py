"""Sidecar writers: data_health.json and identity_events.json"""
import json
import pathlib

from src.integrity import sidecar


def test_write_data_health_creates_valid_json(tmp_path):
    findings = [
        {"id": "F-2025-07-14-0930-44", "interval": "09:30", "queue": "44",
         "classification": "queue_extract_gap", "severity": "high",
         "expected_contacts": None, "observed_contacts": 0, "z_score": None,
         "evidence": {"agents_staffed": ["30128","30143","30157"], "ready_time_seconds_total": 890,
                      "agent_system_handled": 0, "queue_handled": 0},
         "action_taken": "emit_with_annotation", "operator_note": None}
    ]
    path = sidecar.write_data_health(
        out_dir=tmp_path, run_date="2025-07-14", customer="demo",
        findings=findings, intervals_checked=20, cold_start=True, baseline_days=0,
    )
    doc = json.loads(pathlib.Path(path).read_text())
    assert doc["schema_version"] == "1.0"
    assert doc["run_date"] == "2025-07-14"
    assert doc["customer"] == "demo"
    assert doc["summary"]["findings_count"] == 1
    assert doc["summary"]["cold_start"] is True
    assert doc["findings"] == findings


def test_write_identity_events_fills_customer_and_time(tmp_path):
    payload = {
        "schema_version": "1.0", "run_date": "2025-07-14", "customer": None,
        "generated_at": None,
        "summary": {"proposals_count": 0, "new_queues_registered": 0, "disappeared_unmatched": 0},
        "proposals": [], "new_queues": [], "unmatched_disappearances": [],
    }
    path = sidecar.write_identity_events(out_dir=tmp_path, customer="demo", payload=payload)
    doc = json.loads(pathlib.Path(path).read_text())
    assert doc["customer"] == "demo"
    assert doc["generated_at"] is not None
