from pathlib import Path
import textwrap
import subprocess
import sys
import os


def test_shim_dispatches_to_new_pipeline_when_only_vendor(tmp_path):
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "mini.yaml").write_text(textwrap.dedent("""
        slug: mini
        name: Mini
        aliases: []
        category: fixed_schema
        description: d
        sources:
          - kind: html_doc
            role: primary
            url: https://mock.mini/x
    """))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    from lexicon.discover.cache import DiskCache
    DiskCache(cache_dir).put(
        "http", "https://mock.mini/x",
        b"<html><body><table><tr><th>Field</th><th>Description</th></tr>"
        b"<tr><td>holdtime</td><td>Hold time in seconds.</td></tr></table></body></html>",
    )

    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    r = subprocess.run(
        [sys.executable, str(root / "src" / "discover.py"), "mini",
         "--registry", str(registry_dir),
         "--cache-dir", str(cache_dir),
         "--catalogs-dir", str(tmp_path / "catalogs"),
         "--proposed-dir", str(tmp_path / "proposed"),
         "--reports-dir",  str(tmp_path / "reports"),
         "--offline"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "catalogs" / "mini.yaml").exists()


def test_shim_falls_through_to_legacy_from_csv(tmp_path):
    """--from-csv is still handled by legacy code path — smoke test."""
    csv = tmp_path / "demo.csv"
    csv.write_text("INTERVAL_START,holdtime\n2025-06-02T09:00,42\n")
    root = Path(__file__).resolve().parents[3]
    out = tmp_path / "out.yaml"
    r = subprocess.run(
        [sys.executable, str(root / "src" / "discover.py"), "DemoVendor",
         "--from-csv", str(csv), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert out.exists()
    text = out.read_text()
    assert "holdtime" in text
