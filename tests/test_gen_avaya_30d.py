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
