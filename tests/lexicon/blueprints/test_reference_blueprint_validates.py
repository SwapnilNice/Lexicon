"""Load-bearing regression test — the committed Salesforce reference blueprint
must validate cleanly (warnings allowed, no errors).

Any framework change or blueprint change must keep this green.
"""
from pathlib import Path

from lexicon.blueprints.events import load_events, validate_taxonomy
from lexicon.blueprints.parser import parse_blueprint
from lexicon.blueprints.schema import load_schema
from lexicon.blueprints.validator import validate

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT_DIR = ROOT / "ontology" / "blueprints"


def test_events_taxonomy_is_valid():
    """events.yaml itself must have a valid DAG."""
    tax = load_events(BLUEPRINT_DIR / "events.yaml")
    errors = validate_taxonomy(tax)
    assert errors == [], f"events.yaml has taxonomy errors: {errors}"


def test_salesforce_queue_based_blueprint_validates_cleanly():
    """The reference blueprint must produce zero errors (warnings OK)."""
    schema = load_schema(BLUEPRINT_DIR / "schema.yaml")
    events = load_events(BLUEPRINT_DIR / "events.yaml")
    bp = parse_blueprint(BLUEPRINT_DIR / "salesforce" / "queue_based.md")
    errors = validate(bp, schema, events)
    hard_errors = [e for e in errors if e.severity == "error"]
    assert hard_errors == [], (
        "Salesforce reference blueprint has validation errors:\n" +
        "\n".join(f"  {e.section or ''}: {e.message}" for e in hard_errors)
    )


def test_cli_validate_exits_zero():
    """python -m lexicon.blueprints validate must exit 0 on the committed tree."""
    import subprocess
    import sys
    import os
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        [sys.executable, "-m", "lexicon.blueprints", "validate"],
        capture_output=True, text=True, cwd=str(ROOT), env=env,
    )
    assert r.returncode == 0, (
        f"validate CLI exited {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )
