"""Feature B: queue identity resolution — detect renumbers, propose merges."""
import pytest

from src.integrity import identity as ident


def test_agent_overlap_jaccard():
    assert ident.jaccard({"a","b","c"}, {"a","b","c"}) == 1.0
    assert ident.jaccard({"a","b"}, {"c","d"}) == 0.0
    assert abs(ident.jaccard({"a","b","c"}, {"a","b"}) - (2/3)) < 1e-9
    assert ident.jaccard(set(), set()) == 0.0


def test_score_high_when_agent_set_matches():
    disappeared_fp = {
        "agent_set": ["30128","30143","30157"],
        "operating_hours": ["09:00","09:30","10:00"],
        "volume_by_slot": {"MON": {"09:00": 0.4, "09:30": 0.4, "10:00": 0.2}},
        "metadata": {"name": "Sales"},
    }
    new_fp = {
        "agent_set": ["30128","30143","30157"],
        "operating_hours": ["09:00","09:30","10:00"],
        "volume_by_slot": {"MON": {"09:00": 0.4, "09:30": 0.4, "10:00": 0.2}},
        "metadata": {"name": None},
    }
    s = ident.score(disappeared_fp, new_fp)
    assert s["total"] >= 0.85
    assert s["breakdown"]["agent_overlap"] == 1.0


def test_propose_merge_when_44_disappears_and_47_appears_with_same_agents():
    registry = {"version": 1, "queues": [
        {"canonical_id": "Q-SALES",
         "aliases": ["44"],
         "fingerprint": {
             "agent_set": ["30128","30143","30157"],
             "operating_hours": ["09:00","09:30"],
             "volume_by_slot": {"MON": {"09:00": 0.5, "09:30": 0.5}},
             "metadata": {"name": None, "source_last_seen": "2025-07-10"},
         },
         "last_seen": "2025-07-10"},
    ]}
    current_records = {
        "queue": [
            {"day": "2025-07-14", "interval": "09:00", "QueueValue": "47", "ContactsReceived": 40, "HandledLong": 38, "HandleTime": 2400},
            {"day": "2025-07-14", "interval": "09:30", "QueueValue": "47", "ContactsReceived": 45, "HandledLong": 42, "HandleTime": 2600},
        ],
        "agent_queue": [
            {"day": "2025-07-14", "interval": "09:00", "QueueValue": "47", "AgentValue": a, "Handled": 12, "HandleTime": 700}
            for a in ["30128","30143","30157"]
        ],
    }
    result = ident.propose(run_day="2025-07-14", current=current_records, registry=registry, threshold=0.60)
    assert len(result["proposals"]) == 1
    p = result["proposals"][0]
    assert p["disappeared_key"] == "44"
    assert p["new_key"] == "47"
    assert p["canonical_id"] == "Q-SALES"
    assert p["confidence"] >= 0.60


def test_no_proposal_when_new_queue_has_different_agents():
    registry = {"version": 1, "queues": [
        {"canonical_id": "Q-SALES",
         "aliases": ["44"],
         "fingerprint": {
             "agent_set": ["30128","30143","30157"],
             "operating_hours": ["09:00"],
             "volume_by_slot": {"MON": {"09:00": 1.0}},
             "metadata": {"name": None, "source_last_seen": "2025-07-10"},
         },
         "last_seen": "2025-07-10"},
    ]}
    current = {
        "queue": [{"day": "2025-07-14", "interval": "09:00", "QueueValue": "99",
                   "ContactsReceived": 10, "HandledLong": 10, "HandleTime": 500}],
        "agent_queue": [
            {"day": "2025-07-14", "interval": "09:00", "QueueValue": "99", "AgentValue": "99001", "Handled": 10, "HandleTime": 500}
        ],
    }
    result = ident.propose("2025-07-14", current, registry, threshold=0.60)
    assert result["proposals"] == []
    assert len(result["new_queues"]) == 1
    assert result["new_queues"][0]["vendor_key"] == "99"
