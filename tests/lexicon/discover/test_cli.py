import os
from pathlib import Path
import textwrap
import subprocess
import sys


def test_cli_runs_end_to_end(tmp_path):
    """Smoke test: invoke the CLI with a --cache-dir pointing at a pre-seeded
    cache, and verify it produces the three output files.
    """
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
        [sys.executable, "-m", "lexicon.discover", "mini",
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
    assert (tmp_path / "proposed" / "mini.queue.PROPOSED.yaml").exists()
    assert (tmp_path / "reports" / "mini.md").exists()
