"""
Baseline profile builder -- turns canonical history into per-(queue, weekday, slot)
expected values. Slots that are always ~0 do not appear (they cannot trigger).
"""
import pathlib
import statistics
from collections import defaultdict
from datetime import date

import yaml

WEEKDAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _weekday(day_iso: str) -> str:
    return WEEKDAY_NAMES[date.fromisoformat(day_iso).weekday()]


def build(store) -> dict:
    """Read the store's queue history and return a baseline dict.

    Output shape:
        {"version": 1,
         "generated_from_days": <int>,
         "queues": {
             "<QueueValue>": {
                 "weekday_slot": {
                     "MON": {"09:00": {"expected_contacts": .., "std": .., "expected_handled": ..}}
                 }
             }
         }}
    """
    buckets = defaultdict(list)
    days_seen = set()
    for rec in store.read("queue"):
        q = rec["QueueValue"]
        dow = _weekday(rec["day"])
        slot = rec["interval"]
        buckets[(q, dow, slot)].append(rec)
        days_seen.add(rec["day"])

    queues: dict[str, dict] = {}
    for (q, dow, slot), recs in buckets.items():
        contacts = [r.get("ContactsReceived", 0) for r in recs]
        handled = [r.get("HandledLong", 0) for r in recs]
        handletime = [r.get("HandleTime", 0) for r in recs]
        if all(c == 0 for c in contacts):
            continue
        expected_contacts = int(round(statistics.mean(contacts)))
        std = int(round(statistics.pstdev(contacts))) if len(contacts) > 1 else 0
        expected_handled = int(round(statistics.mean(handled)))
        avg_ht = int(round(sum(handletime) / max(1, sum(contacts)))) if sum(contacts) else 0
        queues.setdefault(q, {"weekday_slot": {}})["weekday_slot"].setdefault(dow, {})[slot] = {
            "expected_contacts": expected_contacts,
            "std": std,
            "expected_handled": expected_handled,
            "expected_handletime_avg": avg_ht,
            "sample_count": len(recs),
        }
    return {
        "version": 1,
        "generated_from_days": len(days_seen),
        "queues": queues,
    }


def write(baseline: dict, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(baseline, sort_keys=False, allow_unicode=True))


def read(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text())


def lookup(baseline: dict, queue: str, day_iso: str, interval: str) -> dict | None:
    """Return the expected profile for (queue, day, interval) or None."""
    if not baseline:
        return None
    q = baseline.get("queues", {}).get(queue)
    if not q:
        return None
    dow = _weekday(day_iso)
    return q.get("weekday_slot", {}).get(dow, {}).get(interval)
