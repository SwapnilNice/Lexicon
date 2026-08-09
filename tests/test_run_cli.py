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
    hist = state / "history" / "demo" / "queue.jsonl"
    assert hist.exists()
    lines = hist.read_text().splitlines()
    assert len(lines) > 0
    bl = state / "baselines" / "demo" / "queue_baselines.yaml"
    assert bl.exists()
    reg = state / "queue_registry" / "demo.yaml"
    assert reg.exists()


def test_scenario_run_produces_pipeline_gap_finding(tmp_path):
    healthy, gap = _gen_fixtures(tmp_path)
    state = tmp_path / "state"
    out = tmp_path / "out" / "2025-07-14"
    r1 = _integrity(["--warmup", "--input", str(healthy),
                     "--customer", "demo", "--state-dir", str(state)])
    assert r1.returncode == 0, r1.stderr
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
    assert ie["summary"]["proposals_count"] == 0


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
