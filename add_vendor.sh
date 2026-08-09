#!/usr/bin/env bash
# One command to add a new ACD vendor: DISCOVER -> SCAFFOLD -> PROPOSE.
#
#   ./add_vendor.sh <Vendor> <input> [--engine llm]
#
# <input> can be:
#   *.yaml         an already-made catalog
#   *.csv          a data export (its header becomes the vendor's field list)
#   *.pdf / URL    a vendor document (add --engine llm to read descriptions)
#
# Produces:
#   ontology/<vendor>_dialect.yaml           dialect stub (only if none exists)
#   ontology/proposed/<vendor>.<report>.PROPOSED.yaml   for queue/agentqueue/agentsystem
#
# Then hand-fill the dialect, verify each proposed mapping against a golden,
# and promote to ontology/mappings/ (status: approved).
set -e
VENDOR="$1"; INPUT="$2"; ENGINE_FLAG="$3"
LV=$(echo "$VENDOR" | tr '[:upper:]' '[:lower:]')

# ---- Step 1: DISCOVER (build the catalog unless one was given) ----
case "$INPUT" in
  *.yaml) CAT="$INPUT" ;;
  *.csv)  python3 src/discover.py "$VENDOR" --from-csv "$INPUT"
          CAT="fixtures/vendor_catalogs/$LV.yaml" ;;
  *)      python3 src/discover.py "$VENDOR" --doc "$INPUT" ${ENGINE_FLAG:+--engine llm}
          CAT="fixtures/vendor_catalogs/$LV.yaml" ;;
esac

# ---- Step 2: SCAFFOLD the dialect (skip if the author already has one) ----
# Rerunning the wrapper must never clobber a hand-edited dialect.
DIALECT="ontology/${LV}_dialect.yaml"
if [ -f "$DIALECT" ]; then
  echo "-- dialect exists at $DIALECT (leaving it alone)"
else
  python3 src/scaffold_dialect.py "$VENDOR" --catalog "$CAT"
  echo
  echo "!! $DIALECT is a stub. Fill in per-canonical-field vendor terms and traps,"
  echo "   then flip 'confirmed: true' before trusting sensor output."
fi

echo
echo "=================================================================="
echo " Adding vendor: $VENDOR   (creating 3 mapping files)"
echo "=================================================================="
for R in queue agentqueue agentsystem; do
  OUT="ontology/proposed/$LV.$R.PROPOSED.yaml"
  echo; echo "----- $R -----"
  python3 src/automap.py "$CAT" --vendor "$VENDOR" --report "$R" --engine reference --out "$OUT"
  python3 - "$OUT" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for k, v in d["fields"].items():
    print(f"    {k:<18} = {v}")
PY
done
echo
echo "Done. 3 proposed mapping files in ontology/proposed/ for $VENDOR."
echo "Next: verify each with a golden, then move to ontology/mappings/ (approved)."
