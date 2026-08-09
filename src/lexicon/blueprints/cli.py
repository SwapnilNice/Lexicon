"""`python -m lexicon.blueprints` entrypoint.

Subcommands:
  list                        — enumerate discovered blueprints
  show <platform> <routing>   — print a specific blueprint to stdout
  validate [<path>]           — validate all blueprints (or one path)

Flags:
  --blueprints-dir <path>     — default: ontology/blueprints/
  --schema-path <path>        — default: ontology/blueprints/schema.yaml
  --events-path <path>        — default: ontology/blueprints/events.yaml
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .events import load_events, validate_taxonomy
from .index import discover
from .parser import parse_blueprint, ParserError
from .schema import load_schema
from .validator import validate


ROOT = Path(__file__).resolve().parents[3]


_DEFAULT_FRAMEWORK = ROOT / "ontology" / "blueprints"


def _paths(args) -> tuple[Path, Path, Path]:
    bd = Path(args.blueprints_dir) if args.blueprints_dir else _DEFAULT_FRAMEWORK
    # schema/events always default to the project framework, not to bd,
    # so --blueprints-dir can point at arbitrary directories for testing.
    sp = Path(args.schema_path) if args.schema_path else _DEFAULT_FRAMEWORK / "schema.yaml"
    ep = Path(args.events_path) if args.events_path else _DEFAULT_FRAMEWORK / "events.yaml"
    return bd, sp, ep


def cmd_list(args) -> int:
    bd, _, _ = _paths(args)
    files = discover(bd)
    if not files:
        print(f"(no blueprints found under {bd})")
        return 0
    print(f"{'PLATFORM':16} {'ROUTING':20} {'VERSION':8} VERIFIED")
    for path in files:
        import yaml
        with path.open("r") as fh:
            head = "".join(fh.readlines()[:40])
        try:
            fm_text = head.split("---")[1]
            fm = yaml.safe_load(fm_text) or {}
        except (IndexError, yaml.YAMLError):
            fm = {}
        print(f"{fm.get('platform',''):16} {fm.get('routing_model',''):20} "
              f"{str(fm.get('version','')):8} {fm.get('last_verified','')}")
    return 0


def cmd_show(args) -> int:
    bd, _, _ = _paths(args)
    path = bd / args.platform / f"{args.routing_model}.md"
    if not path.exists():
        print(f"blueprint not found: {path}", file=sys.stderr)
        return 2
    sys.stdout.write(path.read_text())
    return 0


def cmd_validate(args) -> int:
    bd, sp, ep = _paths(args)
    if not sp.exists() or not ep.exists():
        print(f"framework not initialized: {sp} or {ep} missing", file=sys.stderr)
        return 2
    schema = load_schema(sp)
    taxonomy = load_events(ep)
    tax_errors = validate_taxonomy(taxonomy)
    if tax_errors:
        print("events.yaml has errors:")
        for e in tax_errors:
            print(f"  [error] {e}")
        return 1

    if args.path:
        files = [Path(args.path)]
    else:
        files = discover(bd)
    if not files:
        return 0

    total_errors = 0
    for path in files:
        try:
            bp = parse_blueprint(path)
        except ParserError as e:
            print(f"✗ {path}")
            print(f"  [error] {e}")
            total_errors += 1
            continue
        errs = validate(bp, schema, taxonomy)
        errors_only = [e for e in errs if e.severity == "error"]
        warnings = [e for e in errs if e.severity == "warning"]
        if errors_only:
            print(f"✗ {path}")
            for e in errors_only:
                s = f" ({e.section})" if e.section else ""
                print(f"  [error]{s} {e.message}")
            total_errors += 1
        else:
            print(f"✓ {path}")
        for w in warnings:
            s = f" ({w.section})" if w.section else ""
            print(f"  [warning]{s} {w.message}")
    if total_errors:
        print(f"\n✗ {total_errors} blueprint(s) failed validation")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Shared flags available on every subcommand (after or before the subcommand name).
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--blueprints-dir", default=None)
    shared.add_argument("--schema-path", default=None)
    shared.add_argument("--events-path", default=None)

    ap = argparse.ArgumentParser("lexicon.blueprints", parents=[shared])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", parents=[shared])

    sp = sub.add_parser("show", parents=[shared])
    sp.add_argument("platform")
    sp.add_argument("routing_model")

    vp = sub.add_parser("validate", parents=[shared])
    vp.add_argument("path", nargs="?", default=None)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "show":
        return cmd_show(args)
    if args.cmd == "validate":
        return cmd_validate(args)
    return 2
