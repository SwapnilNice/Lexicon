"""
Lexicon VERIFY — grade a PROPOSED mapping against the golden oracle (report-aware).

Runs the proposed formulas through the engine and compares every field, per record,
to the hand-authored golden. Reports which fields PASS and which the expert must FIX.

Usage:
  python src/verify_mapping.py <proposed.map.yaml> <input.csv|json> <golden.xml>
"""
import pathlib
import sys
import yaml
from lxml import etree

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import engine  # noqa: E402


def _leaf(child):
    ts = child.findtext("duration/totalseconds")
    cnt = child.findtext("count")
    pct = child.findtext("percentage")
    v = ts if ts is not None else (cnt if cnt is not None else (pct if pct is not None else (child.text or "").strip()))
    return int(v) if isinstance(v, str) and v.lstrip("-").isdigit() else v


def golden_records(path, cfg, section):
    """{ keytuple: {field: value} } from the golden XML."""
    root = etree.fromstring(pathlib.Path(path).read_text().encode())
    keyfields = [f for f in cfg["order"] if engine.unit_of(f, section) == "key"]
    out = {}
    for data in root.iter(cfg["data"]):
        rec = {}
        for child in data:
            rec[child.tag] = child.text.strip() if engine.unit_of(child.tag, section) == "key" else _leaf(child)
        key = tuple(str(rec.get(k)) for k in keyfields)
        out[key] = rec
    return out, keyfields


def run(proposed_path, input_path, golden_path):
    mapping = yaml.safe_load(pathlib.Path(proposed_path).read_text())
    report = engine.report_of(mapping)
    cfg = engine.REPORTS[report]
    section = cfg["section"]
    proposals = mapping.get("proposals", {})
    rows, _, _ = engine.load_any(input_path)
    gold, keyfields = golden_records(golden_path, cfg, section)

    # match each golden record to an input row by locating the row that contains
    # all of the record's key values (robust to a wrong proposed key mapping)
    def find_row(keytuple):
        want = set(keytuple)
        for r in rows:
            if want <= {str(v) for v in r.values()}:
                return r
        return None

    target = [f for f in cfg["order"] if any(f in g for g in gold.values())]
    passed, failed, unmapped = [], [], []

    print(f"\nVerifying proposed mapping: {proposed_path}   (report: {report})")
    print("=" * 72)
    for key, grec in gold.items():
        row = find_row(key)
        print(f"\nRecord {'/'.join(key)}:")
        for field in target:
            expected = grec.get(field)
            if field not in mapping["fields"]:
                unmapped.append(field)
                print(f"  {field:<18} —          NEEDS MAPPING (AI proposed nothing)")
                continue
            try:
                got = engine.compute_fields({"meta": {"report": report}, "fields": {field: mapping["fields"][field]}}, row)[field]
            except Exception as e:  # noqa: BLE001
                failed.append(field)
                print(f"  {field:<18} ERROR      {e}")
                continue
            ok = str(got) == str(expected)
            (passed if ok else failed).append(field)
            extra = "" if ok else f"  (proposed {mapping['fields'][field]!r} -> {got}, expected {expected})"
            print(f"  {field:<18} {'PASS ' if ok else 'FAIL '}     {got}{extra}")

    fixes = sorted(set(failed) | set(unmapped))
    print("\n" + "=" * 72)
    print(f"RESULT: {len(set(passed) - set(failed))} field(s) correct, {len(fixes)} need expert fix.")
    if fixes:
        print("Expert must review/fix: " + ", ".join(fixes))
        for f in fixes:
            r = proposals.get(f, {})
            if r:
                print(f"   - {f}: proposed={r.get('proposed')} conf={r.get('confidence')} ({r.get('rationale')})")
    else:
        print("All proposed fields match the golden — ready for expert sign-off.")
    return fixes


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3])
