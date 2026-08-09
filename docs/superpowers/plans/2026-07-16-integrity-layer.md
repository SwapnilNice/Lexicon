# Integrity Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stateful Integrity Layer that catches pipeline-gap and queue-renumber failures the existing transform + sensor cannot see, without touching a byte of the working engine, transformers, or existing tests.

**Architecture:** Separate CLI module in `src/integrity/` that reads raw Avaya CSVs, re-derives canonical records via a library call to the existing engine, maintains a 30-day rolling history store, and emits `data_health.json` + `identity_events.json` sidecars. Existing pipeline path is untouched — verified by a regression test.

**Tech Stack:** Python stdlib (csv, json, pathlib, statistics), PyYAML (already in requirements.txt), pytest (existing test framework). No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-07-16-integrity-layer-design.md`

**Repo note:** The project is not currently a git repo. Each task ends with a `git add … && git commit …` step; if you have not run `git init` yet, treat those steps as checkpoint markers (the tests must pass before moving on either way). If you want real commits, run `git init && git add -A && git commit -m "initial"` at the start.

---

## File Structure

**New files (all under project root `/Users/Swapnil.Zade/…/Sparkathon 2026/Lexicon/`):**

| Path | Responsibility |
|---|---|
| `.gitignore` (create or amend) | Exclude `state/` (except `state/.gitkeep`) and `out/` |
| `scripts/gen_avaya_30d.py` | Deterministic synthetic data generator (healthy days + scenarios) |
| `src/integrity/__init__.py` | Package marker |
| `src/integrity/canonical.py` | Wrap engine's `compute_fields` to derive canonical dicts from raw rows |
| `src/integrity/history_store.py` | Append/read/prune `state/history/<customer>/*.jsonl` |
| `src/integrity/baseline.py` | Regenerate `state/baselines/<customer>/queue_baselines.yaml` from history |
| `src/integrity/registry.py` | Load/fingerprint/mutate `state/queue_registry/<customer>.yaml`; ratify CLI |
| `src/integrity/completeness.py` | Feature A classification logic |
| `src/integrity/identity.py` | Feature B fingerprint match + proposal generation |
| `src/integrity/sidecar.py` | Write `data_health.json` + `identity_events.json` |
| `src/integrity/run.py` | Orchestration CLI: normal run + `--warmup` |
| `tests/test_integrity_isolation.py` | Regression fence: engine output stays byte-identical |
| `tests/test_history.py` | History store & baseline unit tests |
| `tests/test_completeness.py` | Feature A tests |
| `tests/test_identity.py` | Feature B tests |
| `tests/test_demo_e2e.py` | End-to-end demo flow |

**Files that must not be modified:** `src/engine.py`, `src/transform_queue.py`, `src/transform_queue_genesys.py`, `src/sensor.py`, `ontology/*.yaml`, any pre-existing test file.

---

## Task 1: Repo scaffolding & `.gitignore`

**Files:**
- Create: `.gitignore` (or amend if exists)
- Create: `src/integrity/__init__.py`
- Create: `state/.gitkeep`
- Create: `out/.gitkeep`

- [ ] **Step 1: Check current state**

Run: `ls .gitignore 2>/dev/null; ls src/integrity 2>/dev/null; ls state 2>/dev/null`
Expected: none of them exist yet (or `.gitignore` exists — you'll amend it).

- [ ] **Step 2: Create/amend `.gitignore`**

If `.gitignore` does not exist, create it with:
```
# Integrity Layer runtime state (per-customer history, baselines, registry)
state/*
!state/.gitkeep

# Integrity Layer per-run outputs
out/*
!out/.gitkeep

# Python
__pycache__/
*.pyc
.pytest_cache/
```

If `.gitignore` exists, append only the lines that aren't already there.

- [ ] **Step 3: Create empty package + placeholders**

Create `src/integrity/__init__.py` with a single line:
```python
"""Lexicon Integrity Layer — stateful data-integrity checks at the ACD→WFM boundary."""
```

Create `state/.gitkeep` (empty file).
Create `out/.gitkeep` (empty file).

- [ ] **Step 4: Verify existing tests still pass (regression baseline)**

Run: `pytest -v`
Expected: all pre-existing tests PASS (record the count — later tasks must maintain it).

- [ ] **Step 5: Commit**

```bash
git add .gitignore src/integrity/__init__.py state/.gitkeep out/.gitkeep
git commit -m "chore: scaffold src/integrity/ package + state/out dirs + .gitignore"
```

---

## Task 2: Synthetic Avaya generator — healthy days

**Files:**
- Create: `scripts/gen_avaya_30d.py`
- Test: `tests/test_gen_avaya_30d.py` (temporary, will delete in Task 3 if not needed; keep if useful)

- [ ] **Step 1: Write failing test**

Create `tests/test_gen_avaya_30d.py`:
```python
"""Sanity checks on the synthetic Avaya generator.

We do NOT check exact numbers (RNG-driven); we check shape and glossary compliance.
"""
import csv
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _run_gen(tmp_path, extra_args):
    out = tmp_path / "avaya_30d"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
         "--start", "2025-06-02", "--days", "3", "--weekdays-only",
         "--interval-min", "30", "--hours", "08:00-18:00",
         "--seed", "42", "--out", str(out)] + list(extra_args),
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    return out


def test_generator_creates_one_folder_per_weekday(tmp_path):
    out = _run_gen(tmp_path, [])
    day_folders = sorted(p.name for p in out.iterdir() if p.is_dir())
    # 2025-06-02 is Monday; 3 weekdays: Mon, Tue, Wed
    assert day_folders == ["2025-06-02", "2025-06-03", "2025-06-04"]


def test_each_day_has_three_reports(tmp_path):
    out = _run_gen(tmp_path, [])
    day = out / "2025-06-02"
    for name in ("queue.csv", "agentqueue.csv", "agentsystem.csv"):
        assert (day / name).exists(), f"missing {name}"


def test_queue_csv_has_expected_columns_and_interval_count(tmp_path):
    out = _run_gen(tmp_path, [])
    with open(out / "2025-06-02" / "queue.csv") as f:
        rows = list(csv.DictReader(f))
    expected_cols = {"INTERVAL_START", "split", "acdcalls", "acceptable", "abncalls",
                     "slvlabns", "acdtime", "holdtime", "acwtime", "anstime", "contactsactive"}
    assert set(rows[0].keys()) == expected_cols
    # 20 intervals (08:00..17:30) × 2 splits = 40 rows
    assert len(rows) == 40


def test_agent_system_reports_staffed_agents(tmp_path):
    """i_stafftime > 0 for every agent in every business-hours interval — required for Feature A."""
    out = _run_gen(tmp_path, [])
    with open(out / "2025-06-02" / "agentsystem.csv") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        assert int(r["i_stafftime"]) > 0, f"agent {r['logid']} not staffed at {r['INTERVAL_START']}"


def test_deterministic_across_runs(tmp_path):
    out1 = _run_gen(tmp_path / "a", [])
    out2 = _run_gen(tmp_path / "b", [])
    a = (out1 / "2025-06-02" / "queue.csv").read_text()
    b = (out2 / "2025-06-02" / "queue.csv").read_text()
    assert a == b, "same --seed must produce identical output"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gen_avaya_30d.py -v`
Expected: FAIL — script does not exist.

- [ ] **Step 3: Write the generator**

Create `scripts/gen_avaya_30d.py`:
```python
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
            skip_queue_rows_for: set[tuple[str, str]] | None = None,
            rename_splits: dict[str, str] | None = None):
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
        per_agent_totals: dict[str, dict[str, int]] = {}  # logid -> {acd, acdtime, hold, acw}

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gen_avaya_30d.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Generate the real 30-day fixture**

Run:
```bash
python scripts/gen_avaya_30d.py --start 2025-06-02 --days 22 --weekdays-only \
    --interval-min 30 --hours 08:00-18:00 --seed 42 \
    --out fixtures/avaya_30d
```
Expected: `fixtures/avaya_30d/` now contains 22 day folders (Mon–Fri, 2025-06-02 through 2025-07-01). Verify with `ls fixtures/avaya_30d/ | wc -l` → 22.

- [ ] **Step 6: Confirm existing tests still pass**

Run: `pytest -v`
Expected: same PASS count as Task 1 Step 4, plus 5 new PASSes from `test_gen_avaya_30d`.

- [ ] **Step 7: Commit**

```bash
git add scripts/gen_avaya_30d.py tests/test_gen_avaya_30d.py fixtures/avaya_30d/
git commit -m "feat(integrity): synthetic Avaya generator + 22 healthy weekdays fixture"
```

---

## Task 3: Synthetic generator — pipeline_gap & queue_renumber scenarios

**Files:**
- Modify: `tests/test_gen_avaya_30d.py` (append two tests)

- [ ] **Step 1: Append failing tests to `tests/test_gen_avaya_30d.py`**

Append:
```python
def test_pipeline_gap_scenario_drops_only_target_rows(tmp_path):
    out = tmp_path / "pg"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
         "--day", "2025-07-14", "--seed", "42",
         "--interval-min", "30", "--hours", "08:00-18:00",
         "--scenario", "pipeline_gap",
         "--gap-interval", "09:30", "--gap-split", "44",
         "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    with open(out / "2025-07-14" / "queue.csv") as f:
        rows = list(csv.DictReader(f))
    # split 44 at 09:30 must be absent; split 13 at 09:30 must be present.
    at_gap = [r for r in rows if r["INTERVAL_START"].endswith("T0930")]
    splits_at_gap = {r["split"] for r in at_gap}
    assert "44" not in splits_at_gap, f"pipeline_gap did not drop split 44 at 09:30: {splits_at_gap}"
    assert "13" in splits_at_gap, "pipeline_gap should only drop the target split"
    # Agent-System must show split-44 agents staffed at 09:30 (that's the whole point).
    with open(out / "2025-07-14" / "agentsystem.csv") as f:
        as_rows = list(csv.DictReader(f))
    staffed_at_gap = [r for r in as_rows if r["INTERVAL_START"].endswith("T0930") and int(r["i_stafftime"]) > 0]
    assert len(staffed_at_gap) == 5, "all 5 agents must be staffed at the gap interval"


def test_queue_renumber_scenario_renames_44_to_47(tmp_path):
    out = tmp_path / "qr"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
         "--day", "2025-07-14", "--seed", "42",
         "--interval-min", "30", "--hours", "08:00-18:00",
         "--scenario", "queue_renumber",
         "--old-split", "44", "--new-split", "47",
         "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    for name in ("queue.csv", "agentqueue.csv"):
        with open(out / "2025-07-14" / name) as f:
            rows = list(csv.DictReader(f))
        splits = {r["split"] for r in rows}
        assert "44" not in splits, f"{name} still contains split 44"
        assert "47" in splits, f"{name} missing split 47"
```

- [ ] **Step 2: Run tests — they should already pass**

The generator was written with scenario support in Task 2, so:

Run: `pytest tests/test_gen_avaya_30d.py -v`
Expected: all 7 tests PASS (5 from Task 2 + 2 new).

If they fail, fix the generator — do not weaken the tests.

- [ ] **Step 3: Generate the two scenario fixtures**

Run:
```bash
python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --interval-min 30 --hours 08:00-18:00 \
    --scenario pipeline_gap --gap-interval 09:30 --gap-split 44 \
    --out fixtures/avaya_30d_scenarios/pipeline_gap

python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --interval-min 30 --hours 08:00-18:00 \
    --scenario queue_renumber --old-split 44 --new-split 47 \
    --out fixtures/avaya_30d_scenarios/queue_renumber
```

Verify:
```
ls fixtures/avaya_30d_scenarios/pipeline_gap/2025-07-14/    # 3 CSVs
ls fixtures/avaya_30d_scenarios/queue_renumber/2025-07-14/  # 3 CSVs
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_gen_avaya_30d.py fixtures/avaya_30d_scenarios/
git commit -m "feat(integrity): scenario fixtures for pipeline_gap and queue_renumber"
```

---

## Task 4: Canonical derivation library (`canonical.py`)

**Files:**
- Create: `src/integrity/canonical.py`
- Test: `tests/test_canonical_layer.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_canonical_layer.py`:
```python
"""Canonical layer wraps engine.compute_fields; must never emit vendor terms."""
import pathlib
import yaml
import pytest

from src.integrity import canonical

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_mapping(name):
    return yaml.safe_load((ROOT / "ontology" / "mappings" / name).read_text())


def test_queue_row_produces_canonical_fields_only():
    mp = _load_mapping("avaya.queue.map.yaml")
    row = {"split": "44", "acdcalls": 48, "acceptable": 40, "abncalls": 3, "slvlabns": 2,
           "acdtime": 2880, "holdtime": 240, "acwtime": 600, "anstime": 480, "contactsactive": 1}
    out = canonical.derive_row(mp, row)
    # canonical keys only — no vendor terms
    forbidden = {"acdtime", "holdtime", "acwtime", "split", "logid", "abncalls", "slvlabns"}
    assert forbidden.isdisjoint(out.keys()), f"vendor terms leaked: {set(out.keys()) & forbidden}"
    # HandleTime = acdtime + holdtime (glossary)
    assert out["HandleTime"] == 3120
    assert out["QueueValue"] == "44"


def test_derive_records_from_csv_file(tmp_path):
    csv_path = tmp_path / "queue.csv"
    csv_path.write_text(
        "INTERVAL_START,split,acdcalls,acceptable,abncalls,slvlabns,acdtime,holdtime,acwtime,anstime,contactsactive\n"
        "20250602T0900,44,48,40,3,2,2880,240,600,480,1\n"
        "20250602T0900,13,20,18,1,1,1500,100,300,260,0\n"
    )
    mp = _load_mapping("avaya.queue.map.yaml")
    recs = canonical.derive_from_csv(mp, csv_path)
    assert len(recs) == 2
    assert {r["interval"] for r in recs} == {"09:00"}
    assert {r["day"] for r in recs} == {"2025-06-02"}
    assert {r["QueueValue"] for r in recs} == {"44", "13"}


def test_missing_vendor_column_raises_clean_error(tmp_path):
    csv_path = tmp_path / "q.csv"
    csv_path.write_text("INTERVAL_START,split,acdcalls\n20250602T0900,44,48\n")
    mp = _load_mapping("avaya.queue.map.yaml")
    with pytest.raises(KeyError):
        canonical.derive_from_csv(mp, csv_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_canonical_layer.py -v`
Expected: FAIL — `src.integrity.canonical` module does not exist.

- [ ] **Step 3: Implement `canonical.py`**

Create `src/integrity/canonical.py`:
```python
"""
Derive canonical records from raw vendor CSVs by reusing the engine's compute_fields.

This is a library wrapper — no XML, no side effects. Keeps the History Store
vendor-neutral, obeying guides/inferential/QUEUE_glossary.md.
"""
import pathlib
from typing import Iterable

from src import engine


def derive_row(mapping: dict, row: dict) -> dict:
    """One vendor row -> one dict of canonical fields (no interval/day metadata)."""
    return engine.compute_fields(mapping, row)


def _parse_interval_start(s: str) -> tuple[str, str]:
    """'20250602T0900' -> ('2025-06-02', '09:00')."""
    day = f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    interval = f"{s[9:11]}:{s[11:13]}"
    return day, interval


def derive_from_csv(mapping: dict, csv_path: pathlib.Path) -> list[dict]:
    """Load a vendor CSV and produce canonical records with (day, interval) metadata attached."""
    rows, _dt, _period = engine.load_csv(str(csv_path))
    out = []
    for r in rows:
        day, interval = _parse_interval_start(r["INTERVAL_START"])
        canon = derive_row(mapping, r)
        canon.update({"day": day, "interval": interval})
        out.append(canon)
    return out


def derive_day_folder(mappings: dict[str, dict], day_folder: pathlib.Path) -> dict[str, list[dict]]:
    """
    Read a day folder (queue.csv, agentqueue.csv, agentsystem.csv) and return
    {report_name: [canonical_records]}.

    `mappings` is keyed by report name: 'queue', 'agentqueue', 'agentsystem'.
    """
    result = {}
    for report, filename in [("queue", "queue.csv"),
                             ("agentqueue", "agentqueue.csv"),
                             ("agentsystem", "agentsystem.csv")]:
        path = day_folder / filename
        if not path.exists():
            result[report] = []
            continue
        result[report] = derive_from_csv(mappings[report], path)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_canonical_layer.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: all previously-green tests remain green; 3 new tests green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/canonical.py tests/test_canonical_layer.py
git commit -m "feat(integrity): canonical derivation wrapper over engine.compute_fields"
```

---

## Task 5: History Store — append, read, prune

**Files:**
- Create: `src/integrity/history_store.py`
- Test: `tests/test_history.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_history.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_history.py -v`
Expected: FAIL — `history_store` does not exist.

- [ ] **Step 3: Implement `history_store.py`**

Create `src/integrity/history_store.py`:
```python
"""
Rolling per-customer canonical history, one JSONL per report.

Canonical-only: refuses to store records that contain known vendor terms.
"""
import json
import pathlib
from datetime import date

FORBIDDEN_TERMS = frozenset({
    # Avaya
    "acdtime", "holdtime", "acwtime", "split", "logid", "abncalls", "slvlabns",
    "anstime", "acceptable", "acdcalls", "i_stafftime", "i_availtime", "ti_auxtime",
    "da_acdcalls", "da_acdtime", "o_acdcalls", "o_acdtime",
    # Genesys
    "tHandle", "tTalk", "tHeld", "tAcw", "queueId", "userId",
})

REPORTS = ("queue", "agent_queue", "agent_system")


class HistoryStore:
    def __init__(self, root: pathlib.Path, customer: str):
        self.root = pathlib.Path(root)
        self.customer = customer
        self.dir = self.root / "history" / customer
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, report: str) -> pathlib.Path:
        assert report in REPORTS, f"unknown report {report}"
        return self.dir / f"{report}.jsonl"

    def append(self, report: str, records: list[dict]) -> None:
        for r in records:
            leaked = FORBIDDEN_TERMS.intersection(r.keys())
            if leaked:
                raise ValueError(f"vendor term(s) leaked into history: {sorted(leaked)}")
        p = self._path(report)
        with p.open("a") as f:
            for r in records:
                f.write(json.dumps(r, sort_keys=True) + "\n")

    def read(self, report: str):
        p = self._path(report)
        if not p.exists():
            return
        with p.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def prune(self, reference_day: str, retention_days: int = 30) -> None:
        """Remove records with day < (reference_day - retention_days)."""
        ref = date.fromisoformat(reference_day)
        keep_from = ref.toordinal() - retention_days
        for report in REPORTS:
            p = self._path(report)
            if not p.exists():
                continue
            kept = []
            with p.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if date.fromisoformat(rec["day"]).toordinal() >= keep_from:
                        kept.append(line)
            with p.open("w") as f:
                for line in kept:
                    f.write(line + "\n")

    def days_present(self, report: str = "queue") -> set[str]:
        return {r["day"] for r in self.read(report)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_history.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/history_store.py tests/test_history.py
git commit -m "feat(integrity): rolling canonical history store with vendor-term guard"
```

---

## Task 6: Baseline profiles — build from history

**Files:**
- Create: `src/integrity/baseline.py`
- Modify: `tests/test_history.py` (append baseline tests)

- [ ] **Step 1: Append failing tests to `tests/test_history.py`**

Append:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_history.py -v`
Expected: NEW tests FAIL (baseline module missing); old tests still pass.

- [ ] **Step 3: Implement `baseline.py`**

Create `src/integrity/baseline.py`:
```python
"""
Baseline profile builder — turns canonical history into per-(queue, weekday, slot)
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
    # bucket: (queue, weekday, slot) -> list of records
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
            continue   # naturally quiet — skip
        expected_contacts = int(round(statistics.mean(contacts)))
        std = int(round(statistics.pstdev(contacts))) if len(contacts) > 1 else 0
        expected_handled = int(round(statistics.mean(handled)))
        handled_intervals = sum(1 for c in contacts if c > 0)
        avg_ht = int(round(sum(handletime) / max(1, sum(contacts)))) if sum(contacts) else 0
        queues.setdefault(q, {"weekday_slot": {}}).setdefault("weekday_slot", queues.get(q, {}).get("weekday_slot", {}))
        queues[q]["weekday_slot"].setdefault(dow, {})[slot] = {
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_history.py -v`
Expected: all tests PASS (4 original + 2 new).

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/baseline.py tests/test_history.py
git commit -m "feat(integrity): baseline profile builder (weekday × slot expected values)"
```

---

## Task 7: Queue Registry — fingerprint + load/save + ratify

**Files:**
- Create: `src/integrity/registry.py`
- Test: `tests/test_registry.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_registry.py`:
```python
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
    # Volume curve normalized to sum=1 over its slots (per weekday)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL — registry module missing.

- [ ] **Step 3: Implement `registry.py`**

Create `src/integrity/registry.py`:
```python
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
    # volume_by_slot: {DOW: {HH:MM: count}} then normalize each DOW to sum=1
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

    # fingerprint each entry from the union of its aliases' history
    for entry in new_queues_by_id.values():
        # Merge fingerprints from all aliases (usually just one)
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
        # renormalize per-DOW curves
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_registry.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/registry.py tests/test_registry.py
git commit -m "feat(integrity): queue registry with fingerprints and human ratification"
```

---

## Task 8: Feature A — Completeness & Cause

**Files:**
- Create: `src/integrity/completeness.py`
- Test: `tests/test_completeness.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_completeness.py`:
```python
"""Feature A: completeness classification."""
import pathlib
import pytest
import yaml

from src.integrity import completeness as comp


def test_cross_report_gap_flagged_day_one_cold_start():
    """No baselines available (cold start) — cross-report contradiction still fires."""
    day = "2025-07-14"
    # Current interval: queue.44 empty, agent_system has 3 agents ready.
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
    # No baselines yet
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
    queue = []  # empty
    as_ = [{"day": day, "interval": "05:00", "AgentValue": "30128", "ReadyTime": 0, "LoginTime": 0, "InternalContacts": 0}]
    baseline = {"queues": {"44": {"weekday_slot": {"MON": {}}}}}
    findings = comp.classify(day, {"queue": queue, "agent_queue": [], "agent_system": as_}, baseline)
    assert findings == []


def test_whole_feed_failure_when_all_queues_collapse():
    day = "2025-07-14"
    # No queue rows at all for 09:30, but agents are staffed & ready
    as_ = [
        {"day": day, "interval": "09:30", "AgentValue": "30128", "ReadyTime": 300, "LoginTime": 1800, "InternalContacts": 0},
        {"day": day, "interval": "09:30", "AgentValue": "30201", "ReadyTime": 300, "LoginTime": 1800, "InternalContacts": 0},
    ]
    baseline = {"queues": {
        "44": {"weekday_slot": {"MON": {"09:30": {"expected_contacts": 50, "std": 5, "expected_handled": 45, "expected_handletime_avg": 60}}}},
        "13": {"weekday_slot": {"MON": {"09:30": {"expected_contacts": 22, "std": 3, "expected_handled": 20, "expected_handletime_avg": 60}}}},
    }}
    findings = comp.classify(day, {"queue": [], "agent_queue": [], "agent_system": as_}, baseline)
    # At least one whole_feed_failure finding
    assert any(f["classification"] == "whole_feed_failure" for f in findings)


def test_genuine_drop_not_flagged():
    """Queue is low AND no agents staffed — this is a real drop, must pass through silently."""
    day = "2025-07-14"
    queue = [{"day": day, "interval": "09:30", "QueueValue": "44", "ContactsReceived": 3, "HandledLong": 3}]
    aq = []
    as_ = [{"day": day, "interval": "09:30", "AgentValue": "30128", "ReadyTime": 0, "LoginTime": 0, "InternalContacts": 0}]
    baseline = {"queues": {"44": {"weekday_slot": {"MON": {"09:30": {"expected_contacts": 50, "std": 5, "expected_handled": 45, "expected_handletime_avg": 60}}}}}}
    findings = comp.classify(day, {"queue": queue, "agent_queue": aq, "agent_system": as_}, baseline)
    # Volume dropped, but agents not staffed → genuine, no flag
    assert findings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_completeness.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `completeness.py`**

Create `src/integrity/completeness.py`:
```python
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
    """Return list of data_health findings.

    `current`: {"queue": [canon rows], "agent_queue": [...], "agent_system": [...]}
    `baseline`: baseline dict (or None for cold start)
    """
    findings: list[dict] = []

    queue_rows = current.get("queue", [])
    as_rows = current.get("agent_system", [])
    intervals = _all_intervals(current)

    for interval in sorted(intervals):
        staffed = _staffed_and_ready_agents(as_rows, interval)
        ready_total = _ready_time_total(as_rows, interval)

        # Whole-feed failure: no queue rows at all at this interval, but agents staffed.
        any_queue_activity = any(r.get("interval") == interval for r in queue_rows)
        if not any_queue_activity and staffed:
            # Only flag if baseline says something was expected somewhere
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
                continue  # do not also emit per-queue findings for this interval

        # Per-queue checks
        # Determine which queues to check at this interval:
        queues_at_interval = {r["QueueValue"] for r in queue_rows if r.get("interval") == interval}
        queues_to_check = queues_at_interval | _known_queues(baseline)

        for q in sorted(queues_to_check):
            observed = _queue_observed_contacts(queue_rows, q, interval)
            handled = _queue_handled(queue_rows, q, interval)
            slot = _baseline_slot(baseline, q, run_day, interval)

            # Cold-start path: no baseline. Cross-report signal only.
            if slot is None:
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

            # Baseline present.
            expected = slot["expected_contacts"]
            std = slot["std"]
            if expected < QUIET_THRESHOLD_CONTACTS:
                continue  # naturally quiet
            trigger = expected - Z_TRIGGER * std
            if observed >= trigger:
                continue  # within expected band

            # Suspect. Classify.
            if staffed and handled == 0:
                classification = "queue_extract_gap"
                severity = "high"
            elif not staffed:
                # Genuine drop — agents weren't there. Do NOT flag.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_completeness.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/completeness.py tests/test_completeness.py
git commit -m "feat(integrity): Feature A — Completeness & Cause classifier"
```

---

## Task 9: Feature B — Queue Identity Resolution

**Files:**
- Create: `src/integrity/identity.py`
- Test: `tests/test_identity.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_identity.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_identity.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `identity.py`**

Create `src/integrity/identity.py`:
```python
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
        # L1 of two prob distributions is in [0,2]
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

    # Match each unseen key to any disappeared key above threshold
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

    # Mark conflicts: any pair of proposals that target the same disappeared_key
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
        "customer": None,      # filled by sidecar writer
        "generated_at": None,  # filled by sidecar writer
        "summary": {
            "proposals_count": len(proposals),
            "new_queues_registered": len(new_queues),
            "disappeared_unmatched": len(unmatched_disappearances),
        },
        "proposals": proposals,
        "new_queues": new_queues,
        "unmatched_disappearances": unmatched_disappearances,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_identity.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/identity.py tests/test_identity.py
git commit -m "feat(integrity): Feature B — queue identity resolution (fingerprint match)"
```

---

## Task 10: Sidecar writers

**Files:**
- Create: `src/integrity/sidecar.py`
- Test: `tests/test_sidecar.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_sidecar.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sidecar.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `sidecar.py`**

Create `src/integrity/sidecar.py`:
```python
"""JSON sidecar writers — data_health.json and identity_events.json."""
import json
import pathlib
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_data_health(out_dir: pathlib.Path, run_date: str, customer: str,
                       findings: list[dict], intervals_checked: int,
                       cold_start: bool, baseline_days: int) -> pathlib.Path:
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": "1.0",
        "run_date": run_date,
        "customer": customer,
        "generated_at": _now_iso(),
        "summary": {
            "intervals_checked": intervals_checked,
            "findings_count": len(findings),
            "cold_start": cold_start,
            "baseline_days_available": baseline_days,
        },
        "findings": findings,
    }
    p = out_dir / "data_health.json"
    p.write_text(json.dumps(doc, indent=2))
    return p


def write_identity_events(out_dir: pathlib.Path, customer: str, payload: dict) -> pathlib.Path:
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["customer"] = customer
    payload["generated_at"] = _now_iso()
    p = out_dir / "identity_events.json"
    p.write_text(json.dumps(payload, indent=2))
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sidecar.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/sidecar.py tests/test_sidecar.py
git commit -m "feat(integrity): data_health + identity_events sidecar writers"
```

---

## Task 11: Orchestration CLI (`run.py`) — normal + warmup

**Files:**
- Create: `src/integrity/run.py`
- Test: `tests/test_run_cli.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_run_cli.py`:
```python
"""End-to-end integrity CLI: warmup then a scenario run."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _gen_fixtures(tmp_path):
    """Generate 5 healthy weekdays and the pipeline_gap scenario."""
    healthy = tmp_path / "avaya_30d"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
         "--start", "2025-06-02", "--days", "5", "--weekdays-only",
         "--interval-min", "30", "--hours", "08:00-18:00",
         "--seed", "42", "--out", str(healthy)],
        check=True,
    )
    gap = tmp_path / "pipeline_gap"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
         "--day", "2025-07-14", "--seed", "42",
         "--interval-min", "30", "--hours", "08:00-18:00",
         "--scenario", "pipeline_gap", "--gap-interval", "09:30", "--gap-split", "44",
         "--out", str(gap)],
        check=True,
    )
    return healthy, gap


def _integrity(args, cwd=None):
    r = subprocess.run(
        [sys.executable, "-m", "src.integrity.run"] + args,
        capture_output=True, text=True, cwd=cwd or ROOT,
    )
    return r


def test_warmup_populates_history_and_baselines(tmp_path):
    healthy, _ = _gen_fixtures(tmp_path)
    state = tmp_path / "state"
    r = _integrity(["--warmup", "--input", str(healthy),
                    "--customer", "demo", "--state-dir", str(state)])
    assert r.returncode == 0, r.stderr
    # history has queue rows
    hist = state / "history" / "demo" / "queue.jsonl"
    assert hist.exists()
    lines = hist.read_text().splitlines()
    assert len(lines) > 0
    # baselines file exists
    bl = state / "baselines" / "demo" / "queue_baselines.yaml"
    assert bl.exists()
    # registry created
    reg = state / "queue_registry" / "demo.yaml"
    assert reg.exists()


def test_scenario_run_produces_pipeline_gap_finding(tmp_path):
    healthy, gap = _gen_fixtures(tmp_path)
    state = tmp_path / "state"
    out = tmp_path / "out" / "2025-07-14"
    # warmup first
    r1 = _integrity(["--warmup", "--input", str(healthy),
                     "--customer", "demo", "--state-dir", str(state)])
    assert r1.returncode == 0, r1.stderr
    # then scenario
    r2 = _integrity(["--input", str(gap / "2025-07-14"),
                     "--customer", "demo", "--state-dir", str(state),
                     "--out", str(out), "--run-date", "2025-07-14"])
    assert r2.returncode == 0, r2.stderr
    dh = json.loads((out / "data_health.json").read_text())
    ie = json.loads((out / "identity_events.json").read_text())
    assert dh["summary"]["findings_count"] >= 1
    gap_finding = [f for f in dh["findings"] if f["classification"] == "queue_extract_gap"]
    assert len(gap_finding) == 1
    f = gap_finding[0]
    assert f["interval"] == "09:30"
    assert f["queue"] == "44"
    assert set(f["evidence"]["agents_staffed"]) >= {"30128","30143","30157"}
    # identity_events should be empty (no renumber in this scenario)
    assert ie["summary"]["proposals_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_cli.py -v`
Expected: FAIL — `src.integrity.run` does not exist.

- [ ] **Step 3: Implement `run.py`**

Create `src/integrity/run.py`:
```python
"""
Integrity Layer CLI — orchestrates canonical derivation + history + Feature A + Feature B.

Usage:
    # Normal run (single day input folder):
    python -m src.integrity.run --input <day-folder> --customer <c> \
        --state-dir <state> --out <out-dir> --run-date YYYY-MM-DD

    # Warmup mode (walks each day-folder under --input, appends canonical to history,
    # skips A/B checks):
    python -m src.integrity.run --warmup --input <root> --customer <c> --state-dir <state>
"""
import argparse
import pathlib
import re
import sys

import yaml

from src.integrity import baseline as bl
from src.integrity import canonical
from src.integrity import completeness as comp
from src.integrity import history_store as hs
from src.integrity import identity as ident
from src.integrity import registry as reg
from src.integrity import sidecar

ROOT = pathlib.Path(__file__).resolve().parents[2]
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_avaya_mappings() -> dict[str, dict]:
    """Load the approved Avaya mappings for the three reports."""
    mapping_dir = ROOT / "ontology" / "mappings"
    return {
        "queue":       yaml.safe_load((mapping_dir / "avaya.queue.map.yaml").read_text()),
        "agentqueue":  yaml.safe_load((mapping_dir / "avaya.agentqueue.map.yaml").read_text()),
        "agentsystem": yaml.safe_load((mapping_dir / "avaya.agentsystem.map.yaml").read_text()),
    }


def _canonical_records_for_history(records_by_report: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Rename engine's per-report canonical dict into the history's report keys and shape.
    engine.compute_fields returns per-canonical-field values keyed by their canonical names,
    plus we attach day/interval. History uses report keys 'queue', 'agent_queue', 'agent_system'.
    """
    return {
        "queue": records_by_report.get("queue", []),
        "agent_queue": records_by_report.get("agentqueue", []),
        "agent_system": records_by_report.get("agentsystem", []),
    }


def _run_day(day_folder: pathlib.Path, mappings: dict[str, dict]) -> dict[str, list[dict]]:
    return canonical.derive_day_folder(mappings, day_folder)


def _warmup(input_root: pathlib.Path, store: hs.HistoryStore, mappings: dict[str, dict]) -> int:
    """Iterate day folders under input_root chronologically; append to history. Returns days seen."""
    days = sorted(p for p in input_root.iterdir() if p.is_dir() and DAY_RE.match(p.name))
    for d in days:
        canonicals = _run_day(d, mappings)
        canonicals = _canonical_records_for_history(canonicals)
        store.append("queue",        canonicals["queue"])
        store.append("agent_queue",  canonicals["agent_queue"])
        store.append("agent_system", canonicals["agent_system"])
    return len(days)


def _print(msg: str):
    print(msg, file=sys.stderr)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Warmup: root containing day folders. Normal: a single day folder.")
    ap.add_argument("--customer", required=True)
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--out", help="Where to write sidecars (normal mode)")
    ap.add_argument("--run-date", help="YYYY-MM-DD (defaults to name of --input folder)")
    ap.add_argument("--warmup", action="store_true")
    ap.add_argument("--retention-days", type=int, default=30)
    ap.add_argument("--merge-threshold", type=float, default=0.60)
    args = ap.parse_args(argv)

    state_dir = pathlib.Path(args.state_dir)
    mappings = _load_avaya_mappings()
    store = hs.HistoryStore(root=state_dir, customer=args.customer)

    if args.warmup:
        n = _warmup(pathlib.Path(args.input), store, mappings)
        # After warmup, regenerate baselines + registry from history
        baseline_dict = bl.build(store)
        bl.write(baseline_dict, state_dir / "baselines" / args.customer / "queue_baselines.yaml")
        reg.rebuild_and_save(store, state_dir, args.customer)
        _print(f"[warmup] appended {n} days for customer={args.customer}")
        return 0

    # Normal run
    input_folder = pathlib.Path(args.input)
    if not args.run_date:
        args.run_date = input_folder.name if DAY_RE.match(input_folder.name) else None
    if not args.run_date:
        _print("--run-date is required when input folder is not a YYYY-MM-DD folder")
        return 2
    if not args.out:
        _print("--out is required in normal mode")
        return 2

    # 1. Derive canonical for the day
    canonicals_by_engine = _run_day(input_folder, mappings)
    canonicals = _canonical_records_for_history(canonicals_by_engine)

    # 2. Load current baseline/registry (may be missing → cold start)
    baseline_path = state_dir / "baselines" / args.customer / "queue_baselines.yaml"
    baseline = bl.read(baseline_path)
    registry = reg.load(state_dir, args.customer)
    cold_start = baseline is None or baseline.get("generated_from_days", 0) < 5
    baseline_days = 0 if baseline is None else baseline.get("generated_from_days", 0)

    # 3. Feature A
    findings = comp.classify(run_day=args.run_date, current=canonicals, baseline=baseline)

    intervals_checked = len({r.get("interval") for r in canonicals["agent_system"] if r.get("interval")})

    # 4. Append this day's canonical to history + prune (so Feature B sees full state)
    store.append("queue",        canonicals["queue"])
    store.append("agent_queue",  canonicals["agent_queue"])
    store.append("agent_system", canonicals["agent_system"])
    store.prune(reference_day=args.run_date, retention_days=args.retention_days)

    # 5. Feature B
    identity_payload = ident.propose(run_day=args.run_date, current=canonicals,
                                     registry=registry, threshold=args.merge_threshold)

    # 6. Regenerate baselines (using the newly-updated history)
    baseline_dict = bl.build(store)
    bl.write(baseline_dict, baseline_path)

    # 7. Sidecars
    out_dir = pathlib.Path(args.out)
    sidecar.write_data_health(out_dir, args.run_date, args.customer,
                              findings, intervals_checked, cold_start, baseline_days)
    sidecar.write_identity_events(out_dir, args.customer, identity_payload)
    _print(f"[integrity] {args.run_date} customer={args.customer} findings={len(findings)} "
           f"proposals={identity_payload['summary']['proposals_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_cli.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green — including all pre-existing tests.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/run.py tests/test_run_cli.py
git commit -m "feat(integrity): orchestration CLI (warmup + per-day integrity pass)"
```

---

## Task 12: Ratify (`registry approve`) CLI + queue-renumber test

**Files:**
- Modify: `src/integrity/registry.py` (add `__main__` CLI)
- Modify: `tests/test_registry.py` (append CLI test)
- Modify: `tests/test_run_cli.py` (append queue-renumber test)

- [ ] **Step 1: Append failing tests**

Append to `tests/test_registry.py`:
```python
def test_registry_approve_cli_appends_alias(tmp_path):
    """`python -m src.integrity.registry approve <events_json> --proposal <id> ...` appends the alias."""
    import subprocess
    import sys
    import json

    # Set up state with a registry
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
```

Append to `tests/test_run_cli.py`:
```python
def test_scenario_run_produces_queue_renumber_proposal(tmp_path):
    """After warming on 44+13, running on a day where only 47+13 appear must propose 44→47."""
    healthy = tmp_path / "avaya_30d"
    import subprocess
    import sys
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
         "--start", "2025-06-02", "--days", "10", "--weekdays-only",
         "--interval-min", "30", "--hours", "08:00-18:00",
         "--seed", "42", "--out", str(healthy)],
        check=True,
    )
    renumber = tmp_path / "queue_renumber"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
         "--day", "2025-07-14", "--seed", "42",
         "--interval-min", "30", "--hours", "08:00-18:00",
         "--scenario", "queue_renumber", "--old-split", "44", "--new-split", "47",
         "--out", str(renumber)],
        check=True,
    )
    state = tmp_path / "state"
    out = tmp_path / "out" / "2025-07-14"
    r1 = _integrity(["--warmup", "--input", str(healthy),
                     "--customer", "demo", "--state-dir", str(state)])
    assert r1.returncode == 0, r1.stderr
    r2 = _integrity(["--input", str(renumber / "2025-07-14"),
                     "--customer", "demo", "--state-dir", str(state),
                     "--out", str(out), "--run-date", "2025-07-14"])
    assert r2.returncode == 0, r2.stderr

    ie = json.loads((out / "identity_events.json").read_text())
    assert ie["summary"]["proposals_count"] >= 1
    props = [p for p in ie["proposals"] if p["new_key"] == "47"]
    assert len(props) == 1
    p = props[0]
    assert p["disappeared_key"] == "44"
    assert p["confidence"] >= 0.60
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_registry.py tests/test_run_cli.py -v`
Expected: two NEW tests FAIL (registry has no `__main__`; the renumber test may already work end-to-end but confirms).

- [ ] **Step 3: Append CLI to `src/integrity/registry.py`**

At the bottom of `src/integrity/registry.py`, append:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py tests/test_run_cli.py -v`
Expected: all tests PASS (including the two new ones).

- [ ] **Step 5: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 6: Commit**

```bash
git add src/integrity/registry.py tests/test_registry.py tests/test_run_cli.py
git commit -m "feat(integrity): registry approve/show CLI + queue_renumber e2e test"
```

---

## Task 13: Isolation regression fence

**Files:**
- Create: `tests/test_integrity_isolation.py`

- [ ] **Step 1: Write the test**

Create `tests/test_integrity_isolation.py`:
```python
"""
Regression fence for the "don't disturb" constraint.

Confirms the existing engine + transformers still produce byte-identical XML
against the golden files after the Integrity Layer is present in the tree.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "fixtures" / "golden"
FIXTURES = ROOT / "fixtures"


def _run_engine(mapping_name, csv_name):
    r = subprocess.run(
        [sys.executable, str(ROOT / "src" / "engine.py"),
         str(ROOT / "ontology" / "mappings" / mapping_name),
         str(FIXTURES / csv_name)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_avaya_queue_xml_bytes_unchanged():
    got = _run_engine("avaya.queue.map.yaml", "avaya_queue_sample.csv")
    expected = (GOLDEN / "Q_060225.0900.expected.xml").read_text()
    assert got == expected, "engine XML output has drifted — integrity layer must not touch this"


def test_avaya_agentqueue_xml_bytes_unchanged():
    got = _run_engine("avaya.agentqueue.map.yaml", "avaya_agentqueue_sample.csv")
    expected = (GOLDEN / "AQ_060225.0900.avaya.expected.xml").read_text()
    assert got == expected


def test_avaya_agentsystem_xml_bytes_unchanged():
    got = _run_engine("avaya.agentsystem.map.yaml", "avaya_agentsystem_sample.csv")
    expected = (GOLDEN / "AS_060225.0900.avaya.expected.xml").read_text()
    assert got == expected


def test_sensor_reports_clean_on_engine_output(tmp_path):
    got = _run_engine("avaya.queue.map.yaml", "avaya_queue_sample.csv")
    xml_path = tmp_path / "out.xml"
    xml_path.write_text(got)
    r = subprocess.run(
        [sys.executable, str(ROOT / "src" / "sensor.py"), str(xml_path)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert r.returncode == 0, f"sensor drift on stock engine output: {r.stdout}\n{r.stderr}"
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_integrity_isolation.py -v`
Expected: 4 tests PASS immediately (no code change needed — the engine was never touched).

If any fail, the layer has drifted from "additive only" — investigate before continuing.

- [ ] **Step 3: Confirm regression fence**

Run: `pytest -v`
Expected: everything green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integrity_isolation.py
git commit -m "test(integrity): regression fence for byte-identical engine output"
```

---

## Task 14: End-to-end demo test + demo runbook

**Files:**
- Create: `tests/test_demo_e2e.py`
- Modify: `DEMO_RUNBOOK.md` (append integrity-layer section)

- [ ] **Step 1: Write the E2E test**

Create `tests/test_demo_e2e.py`:
```python
"""
End-to-end demo flow: mirrors what will be shown live.

1. Generate 22 healthy days + two scenarios
2. Warmup integrity → history + baselines + registry
3. Run pipeline_gap scenario → data_health.json has queue_extract_gap
4. Run queue_renumber scenario → identity_events.json has 44→47 proposal
5. Ratify → registry updated
6. Existing pytest still green (checked by running suite outside this test)
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _run(args, check=True, cwd=None):
    r = subprocess.run(args, capture_output=True, text=True, cwd=cwd or ROOT)
    if check:
        assert r.returncode == 0, r.stderr
    return r


def test_full_demo_flow(tmp_path):
    healthy = tmp_path / "avaya_30d"
    gap = tmp_path / "pipeline_gap"
    ren = tmp_path / "queue_renumber"
    state = tmp_path / "state"
    out_gap = tmp_path / "out" / "gap"
    out_ren = tmp_path / "out" / "renumber"

    # 1. Generate
    _run([sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
          "--start", "2025-06-02", "--days", "22", "--weekdays-only",
          "--interval-min", "30", "--hours", "08:00-18:00",
          "--seed", "42", "--out", str(healthy)])
    _run([sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
          "--day", "2025-07-14", "--seed", "42",
          "--interval-min", "30", "--hours", "08:00-18:00",
          "--scenario", "pipeline_gap", "--gap-interval", "09:30", "--gap-split", "44",
          "--out", str(gap)])
    _run([sys.executable, str(ROOT / "scripts" / "gen_avaya_30d.py"),
          "--day", "2025-07-14", "--seed", "42",
          "--interval-min", "30", "--hours", "08:00-18:00",
          "--scenario", "queue_renumber", "--old-split", "44", "--new-split", "47",
          "--out", str(ren)])

    # 2. Warmup
    _run([sys.executable, "-m", "src.integrity.run", "--warmup",
          "--input", str(healthy), "--customer", "demo", "--state-dir", str(state)])
    assert (state / "history" / "demo" / "queue.jsonl").exists()
    assert (state / "baselines" / "demo" / "queue_baselines.yaml").exists()

    # 3. Pipeline-gap scenario
    _run([sys.executable, "-m", "src.integrity.run",
          "--input", str(gap / "2025-07-14"),
          "--customer", "demo", "--state-dir", str(state),
          "--out", str(out_gap), "--run-date", "2025-07-14"])
    dh = json.loads((out_gap / "data_health.json").read_text())
    gaps = [f for f in dh["findings"] if f["classification"] == "queue_extract_gap"]
    assert gaps, f"no queue_extract_gap finding — findings={dh['findings']}"
    assert gaps[0]["interval"] == "09:30"
    assert gaps[0]["queue"] == "44"

    # 4. Queue-renumber scenario. Reset state to isolate.
    import shutil
    shutil.rmtree(state)
    _run([sys.executable, "-m", "src.integrity.run", "--warmup",
          "--input", str(healthy), "--customer", "demo", "--state-dir", str(state)])
    _run([sys.executable, "-m", "src.integrity.run",
          "--input", str(ren / "2025-07-14"),
          "--customer", "demo", "--state-dir", str(state),
          "--out", str(out_ren), "--run-date", "2025-07-14"])
    ie = json.loads((out_ren / "identity_events.json").read_text())
    props = [p for p in ie["proposals"] if p["disappeared_key"] == "44" and p["new_key"] == "47"]
    assert props, f"no 44→47 proposal — payload={ie}"

    # 5. Ratify
    proposal_id = props[0]["id"]
    _run([sys.executable, "-m", "src.integrity.registry", "approve",
          str(out_ren / "identity_events.json"),
          "--proposal", proposal_id,
          "--customer", "demo", "--state-dir", str(state)])
    import yaml
    reg_doc = yaml.safe_load((state / "queue_registry" / "demo.yaml").read_text())
    sales = next(q for q in reg_doc["queues"] if "44" in q["aliases"])
    assert "47" in sales["aliases"]
```

- [ ] **Step 2: Run E2E test**

Run: `pytest tests/test_demo_e2e.py -v -s`
Expected: PASS.

- [ ] **Step 3: Confirm full regression fence**

Run: `pytest -v`
Expected: all tests green (this is the moment of truth for the "don't disturb" claim).

- [ ] **Step 4: Append integrity section to `DEMO_RUNBOOK.md`**

Append the following to `DEMO_RUNBOOK.md`:
```markdown

## Integrity Layer demo

Prereq: run once to build the healthy fixture and warmup state.

```bash
# Generate 22 healthy weekdays (already committed; rerun if state needs a reset)
python scripts/gen_avaya_30d.py --start 2025-06-02 --days 22 --weekdays-only \
    --interval-min 30 --hours 08:00-18:00 --seed 42 \
    --out fixtures/avaya_30d

# Warmup integrity state
python -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state
```

### Feature A — Pipeline gap

```bash
python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --interval-min 30 --hours 08:00-18:00 \
    --scenario pipeline_gap --gap-interval 09:30 --gap-split 44 \
    --out fixtures/avaya_30d_scenarios/pipeline_gap

python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/pipeline_gap/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14

cat out/2025-07-14/data_health.json     # expect classification=queue_extract_gap at 09:30 for split 44
```

### Feature B — Queue renumber

```bash
python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --interval-min 30 --hours 08:00-18:00 \
    --scenario queue_renumber --old-split 44 --new-split 47 \
    --out fixtures/avaya_30d_scenarios/queue_renumber

# Reset state to isolate demo runs
rm -rf state && python -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state

python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/queue_renumber/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14

cat out/2025-07-14/identity_events.json  # expect 44 → 47 proposal, confidence ≥ 0.60

python -m src.integrity.registry approve out/2025-07-14/identity_events.json \
    --proposal P-2025-07-14-RENAME-0 --customer demo --state-dir state

python -m src.integrity.registry show --customer demo --state-dir state
# 47 is now aliased into Q-SALES
```

### Regression fence

```bash
pytest -v          # every existing test still passes
python src/sensor.py <any-XML>   # sensor stays clean
```
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_demo_e2e.py DEMO_RUNBOOK.md
git commit -m "test(integrity): E2E demo flow + runbook section"
```

---

## Final verification

- [ ] **Run the full suite one more time**

```bash
pytest -v
```

Expected: **every test green**, including all pre-existing tests and every new test from tasks 2–14.

- [ ] **Confirm the sensor is clean on stock outputs**

```bash
python src/engine.py ontology/mappings/avaya.queue.map.yaml fixtures/avaya_queue_sample.csv > /tmp/q.xml
python src/sensor.py /tmp/q.xml
```

Expected: sensor reports no drift.

- [ ] **Confirm success criteria from the spec (§12)**

Walk through the seven bullets in `docs/superpowers/specs/2026-07-16-integrity-layer-design.md` §12 and verify each holds. If any fails, do not consider the plan complete.

---

## Self-review checklist (for the plan author, not the executor)

**Spec coverage** — every spec section is covered:
- §3 Architecture → Tasks 1, 4, 11
- §4 Data model (history JSONL, baseline YAML, registry YAML) → Tasks 5, 6, 7
- §5 Feature A → Task 8
- §6 Feature B → Task 9
- §7 Sidecar schemas → Task 10 + assertions in Tasks 11, 12, 14
- §8 CLI surface → Tasks 11, 12
- §9 Synthetic data → Tasks 2, 3
- §10 Testing plan → Tasks 8, 9, 12, 13, 14
- §11 Out of scope — deliberately not implemented (no task, correct)
- §12 Success criteria → Final verification section

**Placeholder scan** — none present. Every step has complete code or an explicit command.

**Type consistency** — verified:
- `HistoryStore.append(report, records)` — `report` values match `REPORTS` tuple, used consistently in Tasks 5, 11
- `derive_day_folder` returns `{"queue","agentqueue","agentsystem"}` keys; run.py explicitly renames to `{"queue","agent_queue","agent_system"}` for the History Store
- `classify` signature `(run_day, current, baseline)` matches call in run.py
- `propose` signature `(run_day, current, registry, threshold)` matches call in run.py
- `ratify(state_root, customer, canonical_id, new_alias)` — matches CLI in Task 12
- Sidecar writers return the path — not asserted anywhere but not depended on either

Plan is complete.
