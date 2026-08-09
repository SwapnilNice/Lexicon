"""History store: append, read, prune. Vendor-neutral by construction."""
import json
import pathlib

from src.integrity import history_store as hs

FORBIDDEN = {"acdtime", "holdtime", "acwtime", "split", "logid",
             "abncalls", "slvlabns", "anstime", "acceptable", "acdcalls",
             "i_stafftime", "i_availtime", "ti_auxtime"}


def _seed(tmp_path):
    root = tmp_path / "state"
    store = hs.HistoryStore(root=root, customer="demo")
    return store


def test_append_and_read_queue_records(tmp_path):
    store = _seed(tmp_path)
    recs = [
        {"day": "2025-06-02", "interval": "09:00", "QueueValue": "44", "ContactsReceived": 48, "HandleTime": 3120},
        {"day": "2025-06-02", "interval": "09:30", "QueueValue": "44", "ContactsReceived": 52, "HandleTime": 3200},
    ]
    store.append("queue", recs)
    got = list(store.read("queue"))
    assert got == recs


def test_prune_drops_records_older_than_30_days(tmp_path):
    store = _seed(tmp_path)
    store.append("queue", [
        {"day": "2025-05-01", "interval": "09:00", "QueueValue": "44", "ContactsReceived": 10},  # 62 days before ref
        {"day": "2025-06-15", "interval": "09:00", "QueueValue": "44", "ContactsReceived": 20},  # 17 days before ref
    ])
    store.prune(reference_day="2025-07-02", retention_days=30)
    got = list(store.read("queue"))
    assert len(got) == 1
    assert got[0]["day"] == "2025-06-15"


def test_no_vendor_terms_in_stored_records(tmp_path):
    """Contract: history store is canonical-only. If a caller tries to append vendor terms, we reject."""
    store = _seed(tmp_path)
    bad = [{"day": "2025-06-02", "interval": "09:00", "split": "44", "acdtime": 3120}]
    import pytest
    with pytest.raises(ValueError, match="vendor term"):
        store.append("queue", bad)


def test_append_creates_customer_dir(tmp_path):
    store = _seed(tmp_path)
    store.append("agent_system", [{"day": "2025-06-02", "interval": "09:00",
                                   "AgentValue": "30128", "LoginTime": 900}])
    p = tmp_path / "state" / "history" / "demo" / "agent_system.jsonl"
    assert p.exists()
    line = json.loads(p.read_text().strip())
    assert line["AgentValue"] == "30128"


from src.integrity import baseline as bl


def _weekday_of(day_iso: str):
    from datetime import date
    return date.fromisoformat(day_iso).strftime("%a").upper()[:3]  # MON, TUE, ...


def test_baseline_builds_expected_contacts_per_weekday_slot(tmp_path):
    store = _seed(tmp_path)
    # Seed 3 Mondays with roughly stable volume at 09:00 for queue "44".
    for day in ["2025-06-02", "2025-06-09", "2025-06-16"]:
        store.append("queue", [{"day": day, "interval": "09:00",
                                "QueueValue": "44", "ContactsReceived": 50,
                                "HandleTime": 3000, "HandledLong": 45}])
    baseline = bl.build(store)
    assert "44" in baseline["queues"]
    mon = baseline["queues"]["44"]["weekday_slot"]["MON"]
    assert "09:00" in mon
    assert mon["09:00"]["expected_contacts"] == 50
    assert mon["09:00"]["std"] == 0  # identical samples


def test_baseline_slots_with_all_zero_are_omitted(tmp_path):
    """Naturally-quiet slots (always zero) must not appear in baseline."""
    store = _seed(tmp_path)
    for day in ["2025-06-02", "2025-06-03"]:
        store.append("queue", [{"day": day, "interval": "05:00",
                                "QueueValue": "44", "ContactsReceived": 0, "HandledLong": 0}])
    baseline = bl.build(store)
    # 05:00 should NOT appear because all samples are zero
    if "44" in baseline["queues"]:
        mon = baseline["queues"]["44"]["weekday_slot"].get("MON", {})
        assert "05:00" not in mon
