"""
Ubiquitous Language Sensor (advisory) — scans a file for vocabulary drift:
  * forbidden / legacy terms (e.g. 'HandledTime', 'Backlog', 'AHT', 'Utilization')
  * Avaya column names leaking past the adapter boundary into canonical output/code

It PROPOSES; it does not block. Exit code is 0 (advisory) but findings are printed.
Point it at a canonical-layer source file or an emitted XML file.

Usage:
    python src/sensor.py path/to/file            # advisory
    python src/sensor.py path/to/file --strict    # exit 1 if findings (for CI gate)
"""
import re
import sys
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"


def load_watchlist():
    """Merge drift watchlists from every *_dialect.yaml — scales per vendor."""
    forbidden, boundary = set(), set()
    for f in sorted(ONTOLOGY.glob("*_dialect.yaml")):
        wl = (yaml.safe_load(f.read_text()) or {}).get("drift_watchlist", {})
        forbidden.update(wl.get("forbidden_terms", []))
        boundary.update(wl.get("boundary_terms", []))
    return sorted(forbidden), sorted(boundary)


def scan(path: str):
    text = pathlib.Path(path).read_text()
    forbidden, boundary = load_watchlist()
    findings = []
    for term in forbidden:
        for m in re.finditer(rf"\b{re.escape(term)}\b", text):
            line = text[:m.start()].count("\n") + 1
            findings.append((line, "FORBIDDEN_TERM", term))
    for term in boundary:
        for m in re.finditer(rf"\b{re.escape(term)}\b", text):
            line = text[:m.start()].count("\n") + 1
            findings.append((line, "VENDOR_LEAK", term))
    return sorted(set(findings))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    if not args:
        print("usage: python src/sensor.py <file> [--strict]"); sys.exit(2)
    findings = scan(args[0])
    if not findings:
        print(f"[sensor] OK — no vocabulary drift in {args[0]}")
        sys.exit(0)
    print(f"[sensor] {len(findings)} finding(s) in {args[0]}:")
    for line, kind, term in findings:
        hint = "legacy/incorrect term" if kind == "FORBIDDEN_TERM" else "Avaya term past adapter boundary"
        print(f"  line {line:>4}  {kind:<14} '{term}'  ({hint})")
    sys.exit(1 if strict else 0)


if __name__ == "__main__":
    main()
