"""
End-to-end demo flow: mirrors what will be shown live.

1. Generate 22 healthy days + two scenarios
2. Warmup integrity → history + baselines + registry
3. Run pipeline_gap scenario → data_health.json has queue_extract_gap
4. Run queue_renumber scenario → identity_events.json has 44→47 proposal
5. Ratify → registry updated
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
