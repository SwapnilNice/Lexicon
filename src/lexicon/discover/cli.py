"""`python -m lexicon.discover <vendor>` entrypoint.

Flags:
  --registry <dir>       ontology/registry/ by default
  --cache-dir <dir>      state/discovery_cache/ by default
  --catalogs-dir <dir>   fixtures/vendor_catalogs/
  --proposed-dir <dir>   ontology/proposed/
  --reports-dir <dir>    out/discovery_reports/
  --report queue|agentqueue|agentsystem
  --offline              disallow cache writes; fail on cache miss (CI mode)
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .cache import DiskCache
from .llm import LLMClient
from .pipeline import run_pipeline
from .registry import load_registry
from .resolver import resolve_vendor_with_fallback, ResolveError


ROOT = Path(__file__).resolve().parents[3]

DEFAULTS = {
    "registry":     ROOT / "ontology" / "registry",
    "cache_dir":    ROOT / "state" / "discovery_cache",
    "catalogs_dir": ROOT / "fixtures" / "vendor_catalogs",
    "proposed_dir": ROOT / "ontology" / "proposed",
    "reports_dir":  ROOT / "out" / "discovery_reports",
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser("lexicon.discover")
    ap.add_argument("vendor")
    ap.add_argument("--registry",     default=str(DEFAULTS["registry"]))
    ap.add_argument("--cache-dir",    default=str(DEFAULTS["cache_dir"]))
    ap.add_argument("--catalogs-dir", default=str(DEFAULTS["catalogs_dir"]))
    ap.add_argument("--proposed-dir", default=str(DEFAULTS["proposed_dir"]))
    ap.add_argument("--reports-dir",  default=str(DEFAULTS["reports_dir"]))
    ap.add_argument("--report", choices=["queue", "agentqueue", "agentsystem"], default="queue")
    ap.add_argument("--offline", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cache = DiskCache(Path(args.cache_dir), offline=args.offline)
    llm = LLMClient(cache=cache, offline=args.offline)
    try:
        entries = load_registry(Path(args.registry))
        result = resolve_vendor_with_fallback(args.vendor, entries, llm)
    except ResolveError as e:
        print(f"[lexicon.discover] {e}", file=sys.stderr)
        return 2

    r = run_pipeline(
        entry=result.entry,
        cache=cache, llm=llm,
        catalogs_dir=Path(args.catalogs_dir),
        proposed_dir=Path(args.proposed_dir),
        reports_dir=Path(args.reports_dir),
        report=args.report,
    )
    print(f"[lexicon.discover] {result.entry.slug} via {result.resolved_via}: "
          f"{r.n_found}/{r.n_fields} fields")
    print(f"  catalog:  {r.catalog_path}")
    print(f"  proposed: {r.proposed_path}")
    print(f"  report:   {r.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
