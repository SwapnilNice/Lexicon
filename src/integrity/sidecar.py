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
