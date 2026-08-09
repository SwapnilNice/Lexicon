import os
from pathlib import Path
import subprocess
import sys
import textwrap


def _root():
    return Path(__file__).resolve().parents[3]


def _seed(tmp_path):
    (tmp_path / "salesforce").mkdir()
    (tmp_path / "salesforce" / "queue_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        platform_display_name: "Salesforce"
        routing_model: queue_based
        channels: [voice]
        version: "1.0"
        last_verified: 2026-08-09
        platform_version_verified_against: "Spring '26"
        authored_by: "T"
        produces_events: [interaction.received]
        ---
        # Overview
        x

        # Prerequisites
        x

        # Configuration steps
        x

        # Object footprint
        | Concept | Platform object.field | Populated when | Notes |
        |---|---|---|---|
        | routing_entity | Queue.Name | admin creates | n |

        # ACD event mapping

        ### interaction.received
        - **Recorded in:** X
        - **Trigger:** Y
        - **Prerequisite events:** none

        # Validation
        x
    """).lstrip("\n"))
    return tmp_path


def _invoke(*args, cwd, blueprints_dir):
    env = {**os.environ, "PYTHONPATH": str(_root() / "src")}
    return subprocess.run(
        [sys.executable, "-m", "lexicon.blueprints",
         *args, "--blueprints-dir", str(blueprints_dir)],
        capture_output=True, text=True, cwd=str(cwd), env=env,
    )


def test_list_shows_seeded_blueprint(tmp_path):
    bd = _seed(tmp_path)
    r = _invoke("list", cwd=_root(), blueprints_dir=bd)
    assert r.returncode == 0, r.stderr
    assert "salesforce" in r.stdout
    assert "queue_based" in r.stdout


def test_show_prints_the_blueprint(tmp_path):
    bd = _seed(tmp_path)
    r = _invoke("show", "salesforce", "queue_based", cwd=_root(), blueprints_dir=bd)
    assert r.returncode == 0, r.stderr
    assert "# Overview" in r.stdout


def test_validate_all_exits_nonzero_on_seed_blueprint(tmp_path):
    """This uses the framework's real schema.yaml + events.yaml but a synthesized
    blueprint that misses many produces_events. Validator will error on those,
    but the goal here is just to prove the CLI plumbing works — exit non-zero and
    print errors is the correct behavior.
    """
    bd = _seed(tmp_path)
    r = _invoke("validate", cwd=_root(), blueprints_dir=bd)
    assert r.returncode != 0
    assert "error" in r.stdout.lower() or "error" in r.stderr.lower()


def test_validate_missing_blueprints_dir_exits_zero(tmp_path):
    r = _invoke("validate", cwd=_root(), blueprints_dir=tmp_path / "does_not_exist")
    # 0 blueprints found — validator has nothing to check; exits 0.
    assert r.returncode == 0
