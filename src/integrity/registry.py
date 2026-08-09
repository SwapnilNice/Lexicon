"""
Canonical queue registry: identity, fingerprints, aliasing (Feature B ratification).

The registry maps canonical_id -> {aliases (vendor keys), fingerprint, last_seen}.
It is REBUILT from history each run, EXCEPT for aliases, which are only added
via ratify() — that is how a human-approved merge sticks.
"""
import pathlib
from collections import defaultdict
from datetime import date

import yaml


def _weekday_name(day_iso: str) -> str:
    names = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    return names[date.fromisoformat(day_iso).weekday()]


def _canonical_id_for(vendor_key: str) -> str:
    """Deterministic id from a vendor key. Format: Q-<key> (upper)."""
    return f"Q-{vendor_key}"


def load(state_root: pathlib.Path, customer: str) -> dict:
    p = pathlib.Path(state_root) / "queue_registry" / f"{customer}.yaml"
    if not p.exists():
        return {"version": 1, "queues": []}
    return yaml.safe_load(p.read_text())


def save(reg: dict, state_root: pathlib.Path, customer: str) -> None:
    p = pathlib.Path(state_root) / "queue_registry" / f"{customer}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(reg, sort_keys=False, allow_unicode=True))


def fingerprint_from_history(store, vendor_key: str) -> dict:
    """Compute the fingerprint dict for a single vendor key from stored canonical history."""
    vol = defaultdict(lambda: defaultdict(float))
    hours = set()
    last_seen = None
    for rec in store.read("queue"):
        if rec.get("QueueValue") != vendor_key:
            continue
        dow = _weekday_name(rec["day"])
        vol[dow][rec["interval"]] += float(rec.get("ContactsReceived", 0))
        hours.add(rec["interval"])
        last_seen = max(last_seen, rec["day"]) if last_seen else rec["day"]

    normalized = {}
    for dow, slots in vol.items():
        total = sum(slots.values())
        if total <= 0:
            continue
        normalized[dow] = {slot: v / total for slot, v in slots.items()}

    agents = set()
    for rec in store.read("agent_queue"):
        if rec.get("QueueValue") == vendor_key:
            agents.add(rec["AgentValue"])

    return {
        "volume_by_slot": normalized,
        "operating_hours": sorted(hours),
        "agent_set": sorted(agents),
        "metadata": {"name": None, "source_last_seen": last_seen},
    }


def rebuild_and_save(store, state_root: pathlib.Path, customer: str) -> dict:
    """Rebuild fingerprints for every vendor key seen in history, preserving existing aliases."""
    existing = load(state_root, customer)
    alias_map: dict[str, str] = {}  # vendor_key -> canonical_id
    for q in existing["queues"]:
        for a in q["aliases"]:
            alias_map[a] = q["canonical_id"]

    seen_keys = {r["QueueValue"] for r in store.read("queue")}

    new_queues_by_id: dict[str, dict] = {}
    for vk in sorted(seen_keys):
        canonical_id = alias_map.get(vk, _canonical_id_for(vk))
        entry = new_queues_by_id.setdefault(canonical_id, {
            "canonical_id": canonical_id,
            "aliases": [],
            "fingerprint": None,
            "last_seen": None,
        })
        if vk not in entry["aliases"]:
            entry["aliases"].append(vk)

    for entry in new_queues_by_id.values():
        merged_vol: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        merged_agents: set[str] = set()
        merged_hours: set[str] = set()
        last_seen = None
        for alias in entry["aliases"]:
            fp = fingerprint_from_history(store, alias)
            for dow, slots in fp["volume_by_slot"].items():
                for s, v in slots.items():
                    merged_vol[dow][s] += v
            merged_agents.update(fp["agent_set"])
            merged_hours.update(fp["operating_hours"])
            src_last = fp["metadata"].get("source_last_seen")
            if src_last and (last_seen is None or src_last > last_seen):
                last_seen = src_last
        norm_vol = {}
        for dow, slots in merged_vol.items():
            total = sum(slots.values())
            if total > 0:
                norm_vol[dow] = {s: v / total for s, v in slots.items()}
        entry["fingerprint"] = {
            "volume_by_slot": norm_vol,
            "operating_hours": sorted(merged_hours),
            "agent_set": sorted(merged_agents),
            "metadata": {"name": None, "source_last_seen": last_seen},
        }
        entry["last_seen"] = last_seen

    reg = {"version": 1, "queues": list(new_queues_by_id.values())}
    save(reg, state_root, customer)
    return reg


def ratify(state_root: pathlib.Path, customer: str, canonical_id: str, new_alias: str) -> dict:
    """Append `new_alias` to the aliases of `canonical_id`. Raises KeyError if id unknown."""
    reg = load(state_root, customer)
    for q in reg["queues"]:
        if q["canonical_id"] == canonical_id:
            if new_alias not in q["aliases"]:
                q["aliases"].append(new_alias)
            save(reg, state_root, customer)
            return reg
    raise KeyError(f"canonical_id not found: {canonical_id}")


def _cli(argv=None):
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(prog="python -m src.integrity.registry")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_show = sub.add_parser("show", help="Print the registry for a customer")
    ap_show.add_argument("--customer", required=True)
    ap_show.add_argument("--state-dir", required=True)

    ap_approve = sub.add_parser("approve", help="Ratify a Feature B proposal")
    ap_approve.add_argument("events_json", help="Path to identity_events.json")
    ap_approve.add_argument("--proposal", required=True, help="Proposal id, e.g. P-2025-07-14-RENAME-0")
    ap_approve.add_argument("--customer", required=True)
    ap_approve.add_argument("--state-dir", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "show":
        r = load(pathlib.Path(args.state_dir), args.customer)
        print(yaml.safe_dump(r, sort_keys=False))
        return 0

    if args.cmd == "approve":
        events = json.loads(pathlib.Path(args.events_json).read_text())
        proposals = events.get("proposals", [])
        match = next((p for p in proposals if p.get("id") == args.proposal), None)
        if match is None:
            print(f"proposal not found: {args.proposal}", file=sys.stderr)
            return 2
        ratify(pathlib.Path(args.state_dir), args.customer,
               canonical_id=match["canonical_id"], new_alias=match["new_key"])
        print(f"ratified: {match['disappeared_key']} → {match['new_key']} in {match['canonical_id']}")
        return 0

    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
