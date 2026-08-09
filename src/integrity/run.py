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
    """Rename engine's per-report canonical dict into the history's report keys and shape."""
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
        baseline_dict = bl.build(store)
        bl.write(baseline_dict, state_dir / "baselines" / args.customer / "queue_baselines.yaml")
        reg.rebuild_and_save(store, state_dir, args.customer)
        _print(f"[warmup] appended {n} days for customer={args.customer}")
        return 0

    input_folder = pathlib.Path(args.input)
    if not args.run_date:
        args.run_date = input_folder.name if DAY_RE.match(input_folder.name) else None
    if not args.run_date:
        _print("--run-date is required when input folder is not a YYYY-MM-DD folder")
        return 2
    if not args.out:
        _print("--out is required in normal mode")
        return 2

    canonicals_by_engine = _run_day(input_folder, mappings)
    canonicals = _canonical_records_for_history(canonicals_by_engine)

    baseline_path = state_dir / "baselines" / args.customer / "queue_baselines.yaml"
    baseline = bl.read(baseline_path)
    registry = reg.load(state_dir, args.customer)
    cold_start = baseline is None or baseline.get("generated_from_days", 0) < 5
    baseline_days = 0 if baseline is None else baseline.get("generated_from_days", 0)

    findings = comp.classify(run_day=args.run_date, current=canonicals, baseline=baseline)

    intervals_checked = len({r.get("interval") for r in canonicals["agent_system"] if r.get("interval")})

    store.append("queue",        canonicals["queue"])
    store.append("agent_queue",  canonicals["agent_queue"])
    store.append("agent_system", canonicals["agent_system"])
    store.prune(reference_day=args.run_date, retention_days=args.retention_days)

    identity_payload = ident.propose(run_day=args.run_date, current=canonicals,
                                     registry=registry, threshold=args.merge_threshold)

    baseline_dict = bl.build(store)
    bl.write(baseline_dict, baseline_path)

    out_dir = pathlib.Path(args.out)
    sidecar.write_data_health(out_dir, args.run_date, args.customer,
                              findings, intervals_checked, cold_start, baseline_days)
    sidecar.write_identity_events(out_dir, args.customer, identity_payload)
    _print(f"[integrity] {args.run_date} customer={args.customer} findings={len(findings)} "
           f"proposals={identity_payload['summary']['proposals_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
