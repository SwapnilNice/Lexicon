"""Feature A: completeness classification."""
import pathlib
import pytest
import yaml

from src.integrity import completeness as comp


def test_cross_report_gap_flagged_day_one_cold_start():
    """No baselines available (cold start) — cross-report contradiction still fires."""
    day = "2025-07-14"
    current_queue = []  # no rows for split 44 at 09:30
    current_agent_system = [
        {"day": day, "interval": "09:30", "AgentValue": "30128", "ReadyTime": 300, "LoginTime": 1800, "InternalContacts": 0},
        {"day": day, "interval": "09:30", "AgentValue": "30143", "ReadyTime": 290, "LoginTime": 1800, "InternalContacts": 0},
        {"day": day, "interval": "09:30", "AgentValue": "30157", "ReadyTime": 300, "LoginTime": 1800, "InternalContacts": 0},
    ]
    current_agent_queue = [
        {"day": day, "interval": "09:30", "QueueValue": "44", "AgentValue": a, "Handled": 0}
        for a in ["30128", "30143", "30157"]
    ]
    findings = comp.classify(
        run_day=day,
        current={"queue": current_queue, "agent_queue": current_agent_queue, "agent_system": current_agent_system},
        baseline=None,
    )
    assert len(findings) == 1
    f = findings[0]
    assert f["classification"] == "queue_extract_gap"
    assert f["interval"] == "09:30"
    assert set(f["evidence"]["agents_staffed"]) == {"30128", "30143", "30157"}


def test_healthy_day_produces_no_findings():
    day = "2025-07-14"
    queue = [{"day": day, "interval": "09:30", "QueueValue": "44", "ContactsReceived": 50, "HandledLong": 45}]
    aq = [{"day": day, "interval": "09:30", "QueueValue": "44", "AgentValue": "30128", "Handled": 15}]
    as_ = [{"day": day, "interval": "09:30", "AgentValue": "30128", "ReadyTime": 100, "LoginTime": 1800, "InternalContacts": 15}]
    baseline = {"queues": {"44": {"weekday_slot": {"MON": {"09:30": {"expected_contacts": 50, "std": 5, "expected_handled": 45, "expected_handletime_avg": 60}}}}}}
    findings = comp.classify(day, {"queue": queue, "agent_queue": aq, "agent_system": as_}, baseline)
    assert findings == []


def test_naturally_quiet_slot_not_flagged():
    """No baseline entry for a slot => naturally quiet => no flag possible."""
    day = "2025-07-14"
    queue = []
    as_ = [{"day": day, "interval": "05:00", "AgentValue": "30128", "ReadyTime": 0, "LoginTime": 0, "InternalContacts": 0}]
    baseline = {"queues": {"44": {"weekday_slot": {"MON": {}}}}}
    findings = comp.classify(day, {"queue": queue, "agent_queue": [], "agent_system": as_}, baseline)
    assert findings == []


def test_whole_feed_failure_when_all_queues_collapse():
    day = "2025-07-14"
    as_ = [
        {"day": day, "interval": "09:30", "AgentValue": "30128", "ReadyTime": 300, "LoginTime": 1800, "InternalContacts": 0},
        {"day": day, "interval": "09:30", "AgentValue": "30201", "ReadyTime": 300, "LoginTime": 1800, "InternalContacts": 0},
    ]
    baseline = {"queues": {
        "44": {"weekday_slot": {"MON": {"09:30": {"expected_contacts": 50, "std": 5, "expected_handled": 45, "expected_handletime_avg": 60}}}},
        "13": {"weekday_slot": {"MON": {"09:30": {"expected_contacts": 22, "std": 3, "expected_handled": 20, "expected_handletime_avg": 60}}}},
    }}
    findings = comp.classify(day, {"queue": [], "agent_queue": [], "agent_system": as_}, baseline)
    assert any(f["classification"] == "whole_feed_failure" for f in findings)


def test_genuine_drop_not_flagged():
    """Queue is low AND no agents staffed — this is a real drop, must pass through silently."""
    day = "2025-07-14"
    queue = [{"day": day, "interval": "09:30", "QueueValue": "44", "ContactsReceived": 3, "HandledLong": 3}]
    aq = []
    as_ = [{"day": day, "interval": "09:30", "AgentValue": "30128", "ReadyTime": 0, "LoginTime": 0, "InternalContacts": 0}]
    baseline = {"queues": {"44": {"weekday_slot": {"MON": {"09:30": {"expected_contacts": 50, "std": 5, "expected_handled": 45, "expected_handletime_avg": 60}}}}}}
    findings = comp.classify(day, {"queue": queue, "agent_queue": aq, "agent_system": as_}, baseline)
    assert findings == []
