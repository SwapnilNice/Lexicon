"""Queue registry: load, fingerprint from history, aliasing (ratification)."""
import pathlib
import yaml
import pytest

from src.integrity import history_store as hs
from src.integrity import registry as reg


def _seed_history(tmp_path):
    store = hs.HistoryStore(root=tmp_path / "state", customer="demo")
    # Two weeks × Mon-Fri × two intervals × queue 44 with 3 agents
    for day in ["2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05", "2025-06-06",
                "2025-06-09", "2025-06-10", "2025-06-11", "2025-06-12", "2025-06-13"]:
        for interval in ["09:00", "09:30"]:
            store.append("queue", [{"day": day, "interval": interval,
                                    "QueueValue": "44", "ContactsReceived": 50,
                                    "HandledLong": 45, "HandleTime": 3000}])
            for agent in ["30128", "30143", "30157"]:
                store.append("agent_queue", [{"day": day, "interval": interval,
                                              "QueueValue": "44", "AgentValue": agent,
                                              "Handled": 15, "HandleTime": 1000}])
    return store


def test_fingerprint_from_history_captures_agent_set(tmp_path):
    store = _seed_history(tmp_path)
    fp = reg.fingerprint_from_history(store, "44")
    assert set(fp["agent_set"]) == {"30128", "30143", "30157"}
    assert fp["operating_hours"] == ["09:00", "09:30"]
    for dow, slots in fp["volume_by_slot"].items():
        s = sum(slots.values())
        assert abs(s - 1.0) < 1e-6, f"{dow} curve does not sum to 1: {s}"


def test_load_missing_registry_returns_empty(tmp_path):
    r = reg.load(tmp_path / "state", "demo")
    assert r == {"version": 1, "queues": []}


def test_rebuild_creates_registry_entries_for_all_queues(tmp_path):
    store = _seed_history(tmp_path)
    reg.rebuild_and_save(store, tmp_path / "state", "demo")
    r = reg.load(tmp_path / "state", "demo")
    ids = [q["canonical_id"] for q in r["queues"]]
    assert len(ids) == 1
    assert r["queues"][0]["aliases"] == ["44"]


def test_ratify_appends_alias(tmp_path):
    store = _seed_history(tmp_path)
    reg.rebuild_and_save(store, tmp_path / "state", "demo")
    r = reg.load(tmp_path / "state", "demo")
    canonical_id = r["queues"][0]["canonical_id"]
    reg.ratify(tmp_path / "state", "demo", canonical_id=canonical_id, new_alias="47")
    r2 = reg.load(tmp_path / "state", "demo")
    assert "47" in r2["queues"][0]["aliases"]


def test_ratify_rejects_unknown_canonical_id(tmp_path):
    store = _seed_history(tmp_path)
    reg.rebuild_and_save(store, tmp_path / "state", "demo")
    with pytest.raises(KeyError):
        reg.ratify(tmp_path / "state", "demo", canonical_id="DOES-NOT-EXIST", new_alias="99")


def test_registry_approve_cli_appends_alias(tmp_path):
    """`python -m src.integrity.registry approve <events_json> --proposal <id> ...` appends the alias."""
    import subprocess
    import sys
    import json

    store = _seed_history(tmp_path)
    state = tmp_path / "state"
    reg.rebuild_and_save(store, state, "demo")
    r = reg.load(state, "demo")
    canonical_id = r["queues"][0]["canonical_id"]

    events = {
        "schema_version": "1.0",
        "run_date": "2025-07-14",
        "customer": "demo",
        "proposals": [
            {"id": "P-2025-07-14-RENAME-0",
             "disappeared_key": "44",
             "new_key": "47",
             "canonical_id": canonical_id}
        ],
    }
    events_path = tmp_path / "identity_events.json"
    events_path.write_text(json.dumps(events))

    ROOT = pathlib.Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "src.integrity.registry", "approve",
         str(events_path), "--proposal", "P-2025-07-14-RENAME-0",
         "--customer", "demo", "--state-dir", str(state)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr

    updated = reg.load(state, "demo")
    assert "47" in updated["queues"][0]["aliases"]
