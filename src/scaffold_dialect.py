"""
Lexicon SCAFFOLD-DIALECT — bridge between step 1 (discover) and step 2 (author).

Reads a discovered vendor catalog and emits a *stub* dialect file with:
  - every canonical field (queue / agent_queue / agent_system) listed with
    `<vendor>: []`, empty `rule`, `confirmed: false`  — forcing the author to fill
    each mapping deliberately;
  - `drift_watchlist.boundary_terms` pre-populated from the catalog's field
    names (the one thing that IS derivable — every vendor column is a boundary
    term by construction);
  - `# TRAP:` markers next to HandleTime/QueueDelayTime/NotReadyTime, the
    canonical fields where past vendors have burned us (see CLAUDE.md).

What this DOES NOT do: guess vendor-term-to-canonical mappings. That's step 3
(automap). This tool only guarantees the structural skeleton is right.

Usage:
  python src/scaffold_dialect.py <Vendor>                             # reads fixtures/vendor_catalogs/<vendor>.yaml
  python src/scaffold_dialect.py <Vendor> --catalog <path>            # explicit catalog path
  python src/scaffold_dialect.py <Vendor> --media-scope <scope>       # default: immediate_response
  python src/scaffold_dialect.py <Vendor> --force                     # overwrite existing dialect
"""
import argparse
import pathlib
import sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Media requirement values that mean "don't emit this field for this scope".
# `not_required` is kept — the vendor need not provide it, but the field is
# still meaningful and the existing Avaya dialect includes such fields.
SKIP_MEDIA_VALUES = {"not_applicable", "ignored"}


def canonical_fields(media_scope: str):
    """Canonical fields per report, filtered by media scope.

    Reads canonical_wfm.yaml so new canonical fields auto-appear in future
    scaffolds. Drops fields whose media.<scope> is not_applicable/ignored,
    which is what enforces `CLAUDE.md`'s rule that inbound voice must not emit
    SvcLvlPct, BackLog*, RightParty*, WrongParty*.
    """
    spec = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())
    out = {}
    for report in ("queue", "agent_queue", "agent_system"):
        kept = []
        for fname, fdef in (spec.get(report) or {}).items():
            if fname == "meta" or not isinstance(fdef, dict):
                continue
            media = fdef.get("media") or {}
            if media.get(media_scope) in SKIP_MEDIA_VALUES:
                continue
            kept.append(fname)
        out[report] = kept
    return out

# Canonical fields where a trap has historically bitten. Author still writes
# the trap text — we just mark the slot so it can't be silently skipped.
TRAP_HINTS = {
    "HandleTime":     "talk+hold semantics — confirm vendor talk metric EXCLUDES hold before adding",
    "QueueDelayTime": "must be wait-to-answer, not abandon-wait",
    "NotReadyTime":   "must EXCLUDE ACW; watch for per-split double-counting",
    "WorkTime":       "ACW only — never merged into HandleTime",
}


def load_catalog(vendor: str, catalog_path: str | None) -> tuple[pathlib.Path, dict]:
    if catalog_path:
        path = pathlib.Path(catalog_path)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            sys.exit(f"catalog not found: {path}")
    else:
        path = ROOT / "fixtures" / "vendor_catalogs" / f"{vendor.lower()}.yaml"
        if not path.exists():
            candidates = sorted((ROOT / "fixtures" / "vendor_catalogs").glob(f"{vendor.lower()}*.yaml"))
            hint = f" Did you mean one of: {', '.join(c.name for c in candidates)}?" if candidates else ""
            sys.exit(f"no catalog at {path.relative_to(ROOT)}. Pass --catalog <path> explicitly.{hint}")
    return path, yaml.safe_load(path.read_text())


def render(vendor: str, catalog: dict, catalog_path: pathlib.Path, media_scope: str) -> str:
    fields = canonical_fields(media_scope)
    vendor_terms = sorted((catalog.get("fields") or {}).keys())
    sources = (catalog.get("meta") or {}).get("source", [])

    out = []
    out.append(f"# {'=' * 74}")
    out.append(f"# Lexicon — {vendor} Dialect Map  (SCAFFOLD — needs author sign-off)")
    out.append(f"# Generated from {catalog_path.relative_to(ROOT)}")
    out.append(f"# Media scope: {media_scope} (fields not_applicable/ignored for this scope were skipped)")
    out.append(f"#")
    out.append(f"# Every field below is `confirmed: false`. Fill in `<vendor>:` lists and")
    out.append(f"# `rule:` from the catalog, then flip `confirmed: true` once verified against")
    out.append(f"# the vendor's own docs (not just the catalog description).")
    out.append(f"# {'=' * 74}")
    out.append("")
    out.append("meta:")
    out.append(f'  vendor: "{vendor}"')
    out.append(f'  system: "TODO: describe the vendor system + version"')
    out.append(f"  media_scope: {media_scope}")
    if sources:
        out.append("  source:")
        for s in sources:
            name = s.get("name", "")
            ref = s.get("url") or s.get("ref") or ""
            out.append(f'    - name: "{name}"')
            if ref:
                key = "url" if s.get("url") else "ref"
                out.append(f'      {key}: "{ref}"')
    out.append("")

    vendor_key = vendor.lower()
    for report in ("queue", "agent_queue", "agent_system"):
        out.append(f"# {'-' * 72}")
        out.append(f"# {report.upper().replace('_', '-')} -> canonical {report}.*")
        out.append(f"# {'-' * 72}")
        out.append(f"{report}:")
        for fname in fields[report]:
            trap = TRAP_HINTS.get(fname)
            out.append(f"  {fname}:")
            out.append(f"    {vendor_key}: []            # TODO: vendor term(s)")
            out.append(f'    rule: ""                    # TODO: how to compute from vendor term(s)')
            if trap:
                out.append(f'    trap: ""                    # TRAP: {trap}')
            out.append(f"    confirmed: false")
        out.append("")

    out.append("drift_watchlist:")
    out.append("  forbidden_terms:")
    for term in ("HandledTime", "Backlog", "AHT", "Utilization"):
        out.append(f'    - "{term}"')
    out.append("  boundary_terms:    # auto-populated from catalog fields")
    for term in vendor_terms:
        out.append(f'    - "{term}"')
    out.append(f'  boundary_rule: "{vendor} column names must NOT appear in canonical output or canonical-layer code."')
    out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vendor")
    ap.add_argument("--catalog", help="explicit path to the discovered vendor catalog YAML")
    ap.add_argument("--media-scope", default="immediate_response",
                    choices=["immediate_response", "deferrable_response", "outbound_campaign", "outbound"],
                    help="NICE media scope; canonical fields not_applicable/ignored for this scope are skipped")
    ap.add_argument("--force", action="store_true", help="overwrite existing dialect")
    args = ap.parse_args()

    catalog_path, catalog = load_catalog(args.vendor, args.catalog)
    out_path = ROOT / "ontology" / f"{args.vendor.lower()}_dialect.yaml"
    if out_path.exists() and not args.force:
        sys.exit(f"{out_path} already exists; pass --force to overwrite")

    out_path.write_text(render(args.vendor, catalog, catalog_path, args.media_scope))
    print(f"wrote {out_path.relative_to(ROOT)}")
    print(f"  catalog: {catalog_path.relative_to(ROOT)}")
    print(f"  media scope: {args.media_scope}")
    print(f"  {len(catalog.get('fields') or {})} vendor terms captured as boundary_terms")
    print(f"  next: fill in `<vendor>:` lists per canonical field, then run add_vendor.sh")


if __name__ == "__main__":
    main()
