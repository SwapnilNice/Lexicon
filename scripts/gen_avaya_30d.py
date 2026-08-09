#!/usr/bin/env python3
"""
Deterministic synthetic Avaya CMS generator.

Produces one folder per day: <out>/YYYY-MM-DD/{queue,agentqueue,agentsystem}.csv
matching the Avaya CMS shape used by src/transform_queue.py and friends.

Values obey guides/inferential/QUEUE_glossary.md:
  - acdtime = talk only (no hold)
  - holdtime separate
  - acwtime never included in HandleTime
"""
import argparse
import csv
import pathlib
import random
from datetime import date, datetime, timedelta

FLEET = {
    # split: (name, [logids], peak_contacts)
    "44": ("Sales",   ["30128", "30143", "30157"], 50),
    "13": ("Support", ["30201", "30215"],          22),
}

# Bell curves for business hours 08:00..17:30 (30-min intervals)
SALES_CURVE = [0.4, 0.7, 1.0, 1.1, 1.1, 1.1, 1.2, 1.1, 0.9, 0.7,
               0.9, 1.0, 1.1, 1.0, 0.9, 0.8, 0.7, 0.5, 0.4, 0.2]
SUPPORT_CURVE = [0.5, 0.8, 0.9, 1.0, 1.0, 1.0, 0.9, 0.85, 0.7, 0.6,
                 0.7, 0.9, 1.0, 1.0, 0.95, 0.9, 0.8, 0.65, 0.5, 0.3]
CURVES = {"44": SALES_CURVE, "13": SUPPORT_CURVE}

WEEKDAY_FACTOR = {0: 1.05, 1: 1.00, 2: 1.00, 3: 1.00, 4: 0.90}  # Mon..Fri

# Stable per-agent share of their queue (sums to 1.0 within a queue)
AGENT_SHARE = {
    "30128": ("44", 0.40),
    "30143": ("44", 0.35),
    "30157": ("44", 0.25),
    "30201": ("13", 0.55),
    "30215": ("13", 0.45),
}


def iter_intervals(hours: str, interval_min: int):
    start_s, end_s = hours.split("-")
    start = datetime.strptime(start_s, "%H:%M")
    end = datetime.strptime(end_s, "%H:%M")
    cur = start
    while cur < end:
        yield cur.strftime("%H%M")
        cur += timedelta(minutes=interval_min)


def gen_day(day: date, rng: random.Random, interval_min: int, hours: str,
            skip_queue_rows_for=None,
            rename_splits=None):
    """Return (queue_rows, agentqueue_rows, agentsystem_rows).

    skip_queue_rows_for: set of (interval_hhmm, split) rows to omit from queue.csv
                        (used by pipeline_gap scenario).
    rename_splits: {old_split: new_split} — rename in all three reports
                        (used by queue_renumber scenario).
    """
    skip_queue_rows_for = skip_queue_rows_for or set()
    rename_splits = rename_splits or {}
    wf = WEEKDAY_FACTOR[day.weekday()]
    interval_seconds = interval_min * 60

    q_rows, aq_rows, as_rows = [], [], []
    intervals = list(iter_intervals(hours, interval_min))

    for slot_idx, hhmm in enumerate(intervals):
        interval_start = f"{day:%Y%m%d}T{hhmm}"
        per_agent_totals: dict = {}  # logid -> {acd, acdtime, hold, acw}

        for split, (name, agents, peak) in FLEET.items():
            curve_val = CURVES[split][slot_idx]
            noise = 1.0 + rng.gauss(0, 0.08)
            contacts = max(0, round(peak * curve_val * wf * noise))

            talk_avg = max(20, rng.gauss(60, 10))
            hold_avg = max(0, rng.gauss(8, 3))
            acw_avg  = max(5, rng.gauss(25, 5))

            acdtime  = round(contacts * talk_avg)
            holdtime = round(contacts * hold_avg)
            acwtime  = round(contacts * acw_avg)
            abandoned = int(rng.random() < 0.5) * max(0, round(0.05 * contacts * rng.random()))
            handled = contacts  # all contacts handled = acdcalls in the healthy days
            acceptable = max(0, handled - int(0.10 * handled))
            slvlabns = min(abandoned, 1)
            anstime = round(contacts * rng.gauss(8, 2))

            out_split = rename_splits.get(split, split)

            if (hhmm, out_split) not in skip_queue_rows_for:
                q_rows.append({
                    "INTERVAL_START": interval_start,
                    "split": out_split,
                    "acdcalls": handled,
                    "acceptable": acceptable,
                    "abncalls": abandoned,
                    "slvlabns": slvlabns,
                    "acdtime": acdtime,
                    "holdtime": holdtime,
                    "acwtime": acwtime,
                    "anstime": anstime,
                    "contactsactive": 0 if contacts > 0 else 0,
                })

            # Agent-Queue split by stable share
            for logid in agents:
                share = AGENT_SHARE[logid][1]
                a_contacts = round(handled * share)
                a_acdtime  = round(acdtime * share)
                a_hold     = round(holdtime * share)
                a_acw      = round(acwtime * share)
                aq_rows.append({
                    "INTERVAL_START": interval_start,
                    "split": out_split,
                    "logid": logid,
                    "acdcalls": a_contacts,
                    "acdtime": a_acdtime,
                    "holdtime": a_hold,
                    "acwtime": a_acw,
                })
                t = per_agent_totals.setdefault(logid, {"acd": 0, "acdt": 0, "auxt": 0})
                t["acd"] += a_contacts
                t["acdt"] += a_acdtime

        # Agent-System: one row per agent per interval
        for logid in AGENT_SHARE:
            t = per_agent_totals.get(logid, {"acd": 0, "acdt": 0, "auxt": 0})
            aux = round(rng.gauss(90, 20))
            aux = max(0, aux)
            avail = max(0, interval_seconds - t["acdt"] - aux)
            as_rows.append({
                "INTERVAL_START": interval_start,
                "logid": logid,
                "da_acdcalls": t["acd"],
                "da_acdtime":  t["acdt"],
                "i_availtime": avail,
                "ti_auxtime":  aux,
                "o_acdcalls":  0,
                "o_acdtime":   0,
                "i_stafftime": interval_seconds,   # fully staffed for the interval
            })

    return q_rows, aq_rows, as_rows


def write_day(out_dir: pathlib.Path, day: date, q, aq, as_):
    d = out_dir / f"{day:%Y-%m-%d}"
    d.mkdir(parents=True, exist_ok=True)
    for name, rows, cols in [
        ("queue.csv", q, ["INTERVAL_START","split","acdcalls","acceptable","abncalls","slvlabns","acdtime","holdtime","acwtime","anstime","contactsactive"]),
        ("agentqueue.csv", aq, ["INTERVAL_START","split","logid","acdcalls","acdtime","holdtime","acwtime"]),
        ("agentsystem.csv", as_, ["INTERVAL_START","logid","da_acdcalls","da_acdtime","i_availtime","ti_auxtime","o_acdcalls","o_acdtime","i_stafftime"]),
    ]:
        with open(d / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)


def daterange(start: date, days: int, weekdays_only: bool):
    d = start
    count = 0
    while count < days:
        if not weekdays_only or d.weekday() < 5:
            yield d
            count += 1
        d += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=str, help="YYYY-MM-DD (start day)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--weekdays-only", action="store_true")
    ap.add_argument("--interval-min", type=int, default=30)
    ap.add_argument("--hours", type=str, default="08:00-18:00")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, required=True)
    # Scenario overrides (Task 3 exercises these)
    ap.add_argument("--day", type=str, help="Single-day generation (scenarios)")
    ap.add_argument("--scenario", choices=["pipeline_gap", "queue_renumber"])
    ap.add_argument("--gap-interval", type=str, help="e.g. 09:30 (drop this interval from queue.csv)")
    ap.add_argument("--gap-split", type=str, help="split to drop, e.g. 44")
    ap.add_argument("--old-split", type=str)
    ap.add_argument("--new-split", type=str)
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.day:
        target_day = datetime.strptime(args.day, "%Y-%m-%d").date()
        rng = random.Random(args.seed + target_day.toordinal())
        skip = set()
        rename = {}
        if args.scenario == "pipeline_gap":
            assert args.gap_interval and args.gap_split, "pipeline_gap requires --gap-interval and --gap-split"
            hh, mm = args.gap_interval.split(":")
            skip.add((f"{hh}{mm}", args.gap_split))
        elif args.scenario == "queue_renumber":
            assert args.old_split and args.new_split, "queue_renumber requires --old-split and --new-split"
            rename[args.old_split] = args.new_split
        q, aq, as_ = gen_day(target_day, rng, args.interval_min, args.hours, skip, rename)
        write_day(out, target_day, q, aq, as_)
        return

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    for d in daterange(start, args.days, args.weekdays_only):
        rng = random.Random(args.seed + d.toordinal())   # per-day seed keeps determinism modular
        q, aq, as_ = gen_day(d, rng, args.interval_min, args.hours)
        write_day(out, d, q, aq, as_)


if __name__ == "__main__":
    main()
