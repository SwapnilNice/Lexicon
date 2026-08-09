# Demo Runbook — the before/after (≈5 minutes)

Goal: show the same coding agent, same task, one variable (Lexicon), and let the
harness catch a silent, money-losing bug that would otherwise ship.

## Setup (once)
```bash
pip install -r requirements.txt
```

## Act 1 — The silent bug (no Lexicon)
Frame: "A generic agent wired up Avaya using the vendor field names."
```bash
python src/transform_queue_baseline_BUGGY.py fixtures/avaya_queue_sample.csv > out/baseline.xml
```
Point out: it produces valid-looking XML. Now run the gate:
```bash
pytest -v -k baseline          # shows the injected errors are real
python src/sensor.py out/baseline.xml
```
Talking point: `HandleTime` for skill 5001 is **3720** — it folded ACW (600s)
into talk+hold (3120s). Nothing crashed. This inflated AHT would quietly wreck
forecasting. The sensor also flags the `ACWTIME` vendor-term leak.

## Act 2 — With Lexicon
Frame: "Now the agent reads the guide and must pass the gate." (If demoing a live
agent, point it at `CLAUDE.md`; otherwise show the reference transformer.)
```bash
python src/transform_queue.py fixtures/avaya_queue_sample.csv > out/correct.xml
pytest -v                      # all green
python src/sensor.py out/correct.xml   # no drift
```
Talking point: `HandleTime` is now **3120** (talk+hold), ACW sits in `WorkTime`,
no vendor terms leak, output is DTD-valid and matches the golden oracle.

## Act 3 — Drift is caught, not shipped
Frame: "What if someone reintroduces the bug later?"
- Edit `src/transform_queue.py` and put the ACW fold back
  (`HandleTime = talk + hold + acw`).
```bash
pytest -v                      # fails deterministically — the gate blocks it
```
Then revert. To show the sensor's forbidden-term catch, run it on emitted XML
(the sensor scans output and canonical-layer code — the adapter is exempt because
it legitimately reads Avaya columns at the boundary):
```bash
python src/sensor.py out/baseline.xml    # flags the ACWTIME leak in the output
```
Close on: the meaning is now enforced in the pipeline, not left to a reviewer's
memory.

## Act 4 — Two vendors, one ontology (the scale moment)
Frame: "Now a totally different source — Genesys Cloud, JSON, milliseconds — into
the SAME canonical output."
```bash
python src/transform_queue_genesys.py fixtures/genesys_queue_sample.json > out/genesys.xml
pytest -v -k genesys           # all green
python src/sensor.py out/genesys.xml
```
Talking point (the punchline): NICE `HandleTime` = talk + hold. **Avaya** must
NOT add ACW; **Genesys** `tHandle` already INCLUDES ACW and is in milliseconds —
so the same field maps oppositely. A generic agent maps each vendor's own
"handle time" straight across and is wrong both times. The ontology is the only
thing that knows the real target. Adding vendor #3 is a new dialect file, not a
new platform.

## Act 5 — AI in the driving seat (the headline)
Frame: "The expensive part is defining the mapping. Let the AI propose it, and let
the harness catch what it gets wrong."
```bash
# AI reads the vendor docs (catalog) + ontology and PROPOSES a mapping
python src/automap.py fixtures/vendor_catalogs/avaya_hsplit_fields.yaml --vendor Avaya
# the harness grades the proposal against the golden oracle
python src/verify_mapping.py ontology/proposed/avaya.queue.PROPOSED.yaml \
    fixtures/avaya_queue_sample.csv fixtures/golden/Q_060225.0900.expected.xml
```
Talking points:
- Avaya: the AI nails the 1:1 fields; the harness catches `HandleTime` (it forgot
  `+ holdtime`) and the service-level splits. **5 correct, 5 to fix.**
- Now Genesys — run the same two commands with the Genesys catalog/JSON/golden.
  **2 correct, 8 to fix**, and the AI reported **confidence 1.0 on a wrong field.**
  That's the whole thesis: *don't trust the AI's confidence — verify.*
- The expert then fixes only the flagged formulas and promotes the file to
  `ontology/mappings/`. AI proposes, harness verifies, human ratifies.

## Act 6 — Add a brand-new vendor live (the closer)
Frame: "Tomorrow we onboard a new ACD. Watch — no new code."
A new vendor is added with one command — the AI proposes all three report mappings
(Queue, Agent-Queue, Agent-System), reusing the patterns learned from the vendors
already approved; then the harness verifies each against its golden:
```bash
./add_vendor.sh <Vendor> <catalog.yaml>
```
The message: every vendor added makes the next one faster and safer. Discovery
drops from days to minutes; the human only signs off.

## What to say about the numbers (non-circular)
- The golden file was hand-authored by a domain expert (you), independent of the
  transformer — it's an oracle, not a self-graded key.
- Next step beyond the hackathon: add a **held-out** skill/VDN the ontology
  wasn't tuned on, and measure mapping accuracy + reviewer time.

## Real-world hook
The NICE spec's own revision history documents two vocabulary fixes
(`HandledTime` → `HandleTime`; `Backlog` → `BackLog`). That is real, shipped
drift in the vendor's own document — exactly what the sensor exists to prevent.

## Integrity Layer demo

Prereq: run once to build the healthy fixture and warmup state.

```bash
# Generate 22 healthy weekdays (already committed; rerun if state needs a reset)
python scripts/gen_avaya_30d.py --start 2025-06-02 --days 22 --weekdays-only \
    --interval-min 30 --hours 08:00-18:00 --seed 42 \
    --out fixtures/avaya_30d

# Warmup integrity state
python -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state
```

### Feature A — Pipeline gap

```bash
python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --interval-min 30 --hours 08:00-18:00 \
    --scenario pipeline_gap --gap-interval 09:30 --gap-split 44 \
    --out fixtures/avaya_30d_scenarios/pipeline_gap

python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/pipeline_gap/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14

cat out/2025-07-14/data_health.json     # expect classification=queue_extract_gap at 09:30 for split 44
```

### Feature B — Queue renumber

```bash
python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --interval-min 30 --hours 08:00-18:00 \
    --scenario queue_renumber --old-split 44 --new-split 47 \
    --out fixtures/avaya_30d_scenarios/queue_renumber

# Reset state to isolate demo runs
rm -rf state && python -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state

python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/queue_renumber/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14

cat out/2025-07-14/identity_events.json  # expect 44 → 47 proposal, confidence ≥ 0.60

python -m src.integrity.registry approve out/2025-07-14/identity_events.json \
    --proposal P-2025-07-14-RENAME-0 --customer demo --state-dir state

python -m src.integrity.registry show --customer demo --state-dir state
# 47 is now aliased into Q-SALES
```

### Regression fence

```bash
pytest -v          # every existing test still passes
python src/sensor.py <any-XML>   # sensor stays clean
```
