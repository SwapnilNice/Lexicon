"""
Feature B — Queue Identity Resolution.

Detects vendor-key renumbers: a known key disappears, an unseen key appears,
and their fingerprints match closely enough to propose a merge.

Never mutates the registry. Proposals go to identity_events.json.
Ratification is a separate manual step (src.integrity.registry.ratify).
"""
from collections import defaultdict
from datetime import date

WEIGHT_AGENT   = 0.50
WEIGHT_VOLUME  = 0.25
WEIGHT_HOURS   = 0.15
WEIGHT_NAME    = 0.10

DISAPPEAR_WINDOW_INTERVALS = 3   # queue must be absent this many consecutive intervals in its normal window


def jaccard(a, b) -> float:
    A, B = set(a), set(b)
    if not A and not B:
        return 0.0
    return len(A & B) / len(A | B)


def _volume_shape_similarity(a: dict, b: dict) -> float:
    """1 - normalized-L1 across weekdays present in either curve."""
    dows = set(a.keys()) | set(b.keys())
    if not dows:
        return 0.0
    total = 0.0
    for dow in dows:
        slots = set(a.get(dow, {}).keys()) | set(b.get(dow, {}).keys())
        if not slots:
            continue
        l1 = sum(abs(a.get(dow, {}).get(s, 0.0) - b.get(dow, {}).get(s, 0.0)) for s in slots)
        total += max(0.0, 1.0 - l1 / 2.0)
    return total / len(dows)


def _hours_overlap(a: list, b: list) -> float:
    A, B = set(a), set(b)
    if not A and not B:
        return 0.0
    return len(A & B) / len(A | B)


def _name_similarity(a: dict, b: dict) -> float:
    na = (a.get("name") or "").lower()
    nb = (b.get("name") or "").lower()
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def score(fp_disappeared: dict, fp_new: dict) -> dict:
    agent = jaccard(fp_disappeared.get("agent_set", []), fp_new.get("agent_set", []))
    volume = _volume_shape_similarity(fp_disappeared.get("volume_by_slot", {}),
                                      fp_new.get("volume_by_slot", {}))
    hours = _hours_overlap(fp_disappeared.get("operating_hours", []),
                           fp_new.get("operating_hours", []))
    name = _name_similarity(fp_disappeared.get("metadata", {}),
                            fp_new.get("metadata", {}))
    total = (WEIGHT_AGENT * agent + WEIGHT_VOLUME * volume
             + WEIGHT_HOURS * hours + WEIGHT_NAME * name)
    return {
        "total": round(total, 4),
        "breakdown": {
            "agent_overlap": round(agent, 4),
            "volume_shape": round(volume, 4),
            "hours_overlap": round(hours, 4),
            "metadata": round(name, 4),
        },
    }


def _fingerprint_from_current(vendor_key: str, current: dict) -> dict:
    """Provisional fingerprint from the current day only."""
    vol = defaultdict(lambda: defaultdict(float))
    hours = set()
    for r in current.get("queue", []):
        if r.get("QueueValue") != vendor_key:
            continue
        dow = ["MON","TUE","WED","THU","FRI","SAT","SUN"][date.fromisoformat(r["day"]).weekday()]
        vol[dow][r["interval"]] += float(r.get("ContactsReceived", 0))
        hours.add(r["interval"])
    normalized = {}
    for dow, slots in vol.items():
        total = sum(slots.values())
        if total > 0:
            normalized[dow] = {s: v / total for s, v in slots.items()}
    agents = sorted({r["AgentValue"] for r in current.get("agent_queue", []) if r.get("QueueValue") == vendor_key})
    return {
        "agent_set": agents,
        "operating_hours": sorted(hours),
        "volume_by_slot": normalized,
        "metadata": {"name": None},
    }


def _keys_present_today(current: dict) -> set[str]:
    return {r["QueueValue"] for r in current.get("queue", [])}


def _keys_in_registry(registry: dict) -> set[str]:
    return {a for q in registry.get("queues", []) for a in q.get("aliases", [])}


def _registry_index(registry: dict) -> dict[str, dict]:
    return {a: q for q in registry.get("queues", []) for a in q.get("aliases", [])}


def propose(run_day: str, current: dict, registry: dict, threshold: float = 0.60) -> dict:
    """Return identity_events payload (schema per spec §7.2)."""
    known = _keys_in_registry(registry)
    today = _keys_present_today(current)

    disappeared = sorted(known - today)
    unseen = sorted(today - known)

    reg_by_alias = _registry_index(registry)

    proposals = []
    new_queues = []
    proposal_ix = 0

    for new_key in unseen:
        fp_new = _fingerprint_from_current(new_key, current)
        best = None
        for old_key in disappeared:
            old_entry = reg_by_alias[old_key]
            s = score(old_entry["fingerprint"], fp_new)
            if s["total"] >= threshold and (best is None or s["total"] > best["score"]["total"]):
                best = {"old_key": old_key, "entry": old_entry, "score": s}
        if best:
            pid = f"P-{run_day}-RENAME-{proposal_ix}"
            proposal_ix += 1
            proposals.append({
                "id": pid,
                "kind": "queue_renumber_merge",
                "disappeared_key": best["old_key"],
                "new_key": new_key,
                "canonical_id": best["entry"]["canonical_id"],
                "confidence": best["score"]["total"],
                "score_breakdown": best["score"]["breakdown"],
                "evidence": {
                    "shared_agents": sorted(set(best["entry"]["fingerprint"].get("agent_set", []))
                                            & set(fp_new.get("agent_set", []))),
                    "disappeared_last_seen": best["entry"].get("last_seen"),
                    "new_key_first_seen": run_day,
                },
                "recommended_action": "propose_alias",
                "status": "pending_review",
                "conflicts_with": [],
            })
        else:
            new_queues.append({
                "vendor_key": new_key,
                "first_seen": run_day,
                "provisional_fingerprint": fp_new,
            })

    by_old: dict[str, list[dict]] = defaultdict(list)
    for p in proposals:
        by_old[p["disappeared_key"]].append(p)
    for old_key, group in by_old.items():
        if len(group) > 1:
            ids = [g["id"] for g in group]
            for g in group:
                g["conflicts_with"] = [i for i in ids if i != g["id"]]

    unmatched_disappearances = [k for k in disappeared
                                if not any(p["disappeared_key"] == k for p in proposals)]

    return {
        "schema_version": "1.0",
        "run_date": run_day,
        "customer": None,
        "generated_at": None,
        "summary": {
            "proposals_count": len(proposals),
            "new_queues_registered": len(new_queues),
            "disappeared_unmatched": len(unmatched_disappearances),
        },
        "proposals": proposals,
        "new_queues": new_queues,
        "unmatched_disappearances": unmatched_disappearances,
    }
