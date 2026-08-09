"""Test --engine lexicon shim in automap.py (Task 23)."""
from pathlib import Path
import subprocess
import sys
import textwrap
import yaml


def test_lexicon_engine_produces_proposed_file(tmp_path):
    catalog_path = tmp_path / "cat.yaml"
    catalog_path.write_text(textwrap.dedent("""
        meta:
          vendor: fixtures_avaya_mini
          resolved_via: manual
        fields:
          split:
            description: "Split/skill number, the queue key."
            unit: key
            semantic_tags: [{tag: queue_key_like, weight: 0.9}]
          acdtime:
            description: "Talk time of ACD calls. Does NOT include holdtime."
            unit: duration_seconds
            semantic_tags: [{tag: talk_time_like, weight: 0.9}]
            traps: [{kind: exclusion, target: hold_time, evidence: 'does NOT include holdtime'}]
          holdtime:
            description: "Hold time on ACD calls, in seconds."
            unit: duration_seconds
            semantic_tags: [{tag: hold_time_like, weight: 0.9}]
    """))
    out_path = tmp_path / "proposed.yaml"
    root = Path(__file__).resolve().parents[3]
    r = subprocess.run(
        [sys.executable, str(root / "src" / "automap.py"), str(catalog_path),
         "--vendor", "MiniVendor", "--engine", "lexicon",
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    data = yaml.safe_load(out_path.read_text())
    assert data["fields"]["HandleTime"] == "acdtime + holdtime"
