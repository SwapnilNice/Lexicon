"""
Feature A — Completeness & Cause.

Classifies suspect intervals as: whole_feed_failure, queue_extract_gap,
extract_job_error, or genuine_drop (which is silent — no finding).

Cold-start (no baseline): the cross-report contradiction check still runs and
catches queue_extract_gap purely from the current interval's three feeds.
"""
from collections import defaultdict
from datetime import date

QUIET_THRESHOLD_CONTACTS = 3
Z_TRIGGER = 3.0    # observed < expected - Z_TRIGGER*std → suspect
READY_TIME_MIN_SECONDS = 60   # agent counted as "ready" if ReadyTime + InternalHandleTime >= this


def _weekday(day_iso: str) -> str:
    return ["MON","TUE","WED","THU","FRI","SAT","SUN"][date.fromisoformat(day_iso).weekday()]


def _baseline_slot(baseline, queue, day_iso, interval):
    if not baseline:
        return None
    q = baseline.get("queues", {}).get(queue)
    if not q:
        return None
    return q.get("weekday_slot", {}).get(_weekday(day_iso), {}).get(interval)


def _staffed_and_ready_agents(agent_system_rows, interval):
    """Return list of AgentValues with meaningful staffing at this interval."""
    return sorted({r["AgentValue"] for r in agent_system_rows
                   if r.get("interval") == interval
                   and (int(r.get("ReadyTime", 0)) + int(r.get("InternalHandleTime", 0))) >= READY_TIME_MIN_SECONDS})


def _ready_time_total(agent_system_rows, interval):
    return sum(int(r.get("ReadyTime", 0)) for r in agent_system_rows if r.get("interval") == interval)


def _queue_handled(queue_rows, queue, interval):
    return sum(int(r.get("HandledLong", 0)) + int(r.get("HandledShort", 0))
               for r in queue_rows if r.get("QueueValue") == queue and r.get("interval") == interval)


def _queue_observed_contacts(queue_rows, queue, interval):
    return sum(int(r.get("ContactsReceived", 0))
               for r in queue_rows if r.get("QueueValue") == queue and r.get("interval") == interval)


def _all_intervals(current) -> set[str]:
    out = set()
    for report in ("queue", "agent_queue", "agent_system"):
        for r in current.get(report, []):
            if "interval" in r:
                out.add(r["interval"])
    return out


def _known_queues(baseline) -> set[str]:
    if not baseline:
        return set()
    return set(baseline.get("queues", {}).keys())


def classify(run_day: str, current: dict, baseline: dict | None) -> list[dict]:
    """Return list of data_health findings."""
    findings: list[dict] = []

    queue_rows = current.get("queue", [])
    as_rows = current.get("agent_system", [])
    intervals = _all_intervals(current)

    for interval in sorted(intervals):
        staffed = _staffed_and_ready_agents(as_rows, interval)
        ready_total = _ready_time_total(as_rows, interval)

        any_queue_activity = any(r.get("interval") == interval for r in queue_rows)
        if not any_queue_activity and staffed:
            expected_anywhere = False
            affected = []
            for q in _known_queues(baseline):
                slot = _baseline_slot(baseline, q, run_day, interval)
                if slot and slot["expected_contacts"] >= QUIET_THRESHOLD_CONTACTS:
                    expected_anywhere = True
                    affected.append(q)
            if expected_anywhere:
                findings.append({
                    "id": f"F-{run_day}-{interval.replace(':','')}-WHOLE",
                    "interval": interval,
                    "queue": None,
                    "classification": "whole_feed_failure",
                    "severity": "high",
                    "expected_contacts": None,
                    "observed_contacts": 0,
                    "z_score": None,
                    "evidence": {
                        "agents_staffed": staffed,
                        "ready_time_seconds_total": ready_total,
                        "affected_queues": sorted(affected),
                    },
                    "action_taken": "emit_with_annotation",
                    "operator_note": None,
                })
                continue

        queues_at_interval = {r["QueueValue"] for r in queue_rows if r.get("interval") == interval}
        aq_rows = current.get("agent_queue", [])
        queues_in_agent_queue = {r["QueueValue"] for r in aq_rows if r.get("interval") == interval}
        queues_to_check = queues_at_interval | _known_queues(baseline) | queues_in_agent_queue

        for q in sorted(queues_to_check):
            observed = _queue_observed_contacts(queue_rows, q, interval)
            handled = _queue_handled(queue_rows, q, interval)
            slot = _baseline_slot(baseline, q, run_day, interval)

            if slot is None:
                # Cold start path: cross-report only
                # Fire if queue appears in agent_queue but not in queue report,
                # and agents are staffed overall
                if q not in queues_at_interval and staffed and ready_total >= READY_TIME_MIN_SECONDS:
                    findings.append({
                        "id": f"F-{run_day}-{interval.replace(':','')}-{q}",
                        "interval": interval,
                        "queue": q,
                        "classification": "queue_extract_gap",
                        "severity": "high",
                        "expected_contacts": None,
                        "observed_contacts": 0,
                        "z_score": None,
                        "evidence": {
                            "agents_staffed": staffed,
                            "ready_time_seconds_total": ready_total,
                            "agent_system_handled": sum(int(r.get("InternalContacts",0)) for r in as_rows if r.get("interval")==interval),
                            "queue_handled": 0,
                        },
                        "action_taken": "emit_with_annotation",
                        "operator_note": None,
                    })
                continue

            expected = slot["expected_contacts"]
            std = slot["std"]
            if expected < QUIET_THRESHOLD_CONTACTS:
                continue
            trigger = expected - Z_TRIGGER * std
            if observed >= trigger:
                continue

            if staffed and handled == 0:
                classification = "queue_extract_gap"
                severity = "high"
            elif not staffed:
                # Genuine drop — no flag
                continue
            else:
                classification = "low_volume_no_signal"
                severity = "medium"

            z = (observed - expected) / std if std > 0 else -999.0
            findings.append({
                "id": f"F-{run_day}-{interval.replace(':','')}-{q}",
                "interval": interval,
                "queue": q,
                "classification": classification,
                "severity": severity,
                "expected_contacts": expected,
                "observed_contacts": observed,
                "z_score": round(z, 2),
                "evidence": {
                    "agents_staffed": staffed,
                    "ready_time_seconds_total": ready_total,
                    "agent_system_handled": sum(int(r.get("InternalContacts",0)) for r in as_rows if r.get("interval")==interval),
                    "queue_handled": handled,
                },
                "action_taken": "emit_with_annotation",
                "operator_note": None,
            })

    return findings
