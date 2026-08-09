# Adding a new vendor — step-by-step terminal walkthrough

This is the "monkey-see-monkey-do" version. Every step shows what you type,
what appears on the screen, and what you do next. Replace `Acme` with your
real vendor name (`Cisco_UCCE`, `Five9`, etc.) throughout.

---

## Before you start

You need ONE of these three input types for your vendor:

- A **CSV file** with a header row of the vendor's column names, OR
- A **PDF** of the vendor's schema/database reference documentation, OR
- A **URL** to that documentation online.

Also have this open in a browser tab or PDF viewer while you work:
- Your vendor's schema documentation (the SAME PDF or URL — you'll consult
  it later when filling in the dialect).

That's it. Now the recipe.

---

## Step 1 — Run one command. Wait.

**You type:**

```bash
./add_vendor.sh Acme path/to/acme_schema.pdf --engine llm
```

(If you have a CSV instead: `./add_vendor.sh Acme path/to/acme_export.csv`.
No `--engine llm` needed for CSVs.)

**What appears on screen** (over ~30-60 seconds):

```
[discover] reading path/to/acme_schema.pdf
[discover] wrote fixtures/vendor_catalogs/acme.yaml (42 fields)

wrote ontology/acme_dialect.yaml
  catalog: fixtures/vendor_catalogs/acme.yaml
  media scope: immediate_response
  42 vendor terms captured as boundary_terms

!! ontology/acme_dialect.yaml is a stub. Fill in per-canonical-field vendor
   terms and traps, then flip 'confirmed: true' before trusting sensor output.

==================================================================
 Adding vendor: Acme   (creating 3 mapping files)
==================================================================

----- queue -----
[automap] wrote ontology/proposed/acme.queue.PROPOSED.yaml
    QueueValue         = SkillGroupID
    HandleTime         = TalkTime
    HoldTime           = HoldTime
    ...

----- agentqueue -----
[automap] wrote ontology/proposed/acme.agentqueue.PROPOSED.yaml
    ...

----- agentsystem -----
[automap] wrote ontology/proposed/acme.agentsystem.PROPOSED.yaml
    ...

Done. 3 proposed mapping files in ontology/proposed/ for Acme.
Next: verify each with a golden, then move to ontology/mappings/ (approved).
```

**What just happened:** Three files got created for you automatically:

1. `fixtures/vendor_catalogs/acme.yaml` — the vendor field inventory.
2. `ontology/acme_dialect.yaml` — the dialect **stub** (empty, waits for you).
3. `ontology/proposed/acme.queue.PROPOSED.yaml` (plus `.agentqueue`, `.agentsystem`)
   — the AI's guessed mappings.

**What you do next:** Nothing yet. Go to Step 2.

---

## Step 2 — Open two files side by side in your editor

**You open in your editor:**

- **Left panel**: `fixtures/vendor_catalogs/acme.yaml` (the vendor's field list)
- **Right panel**: `ontology/acme_dialect.yaml` (the empty stub you're going to fill in)

Also have `ontology/canonical_wfm.yaml` open in a third tab — you'll reference
it to see what each NICE canonical field means.

**What you see in `ontology/acme_dialect.yaml`** (the right panel, one field at a time):

```yaml
queue:
  QueueValue:
    acme: []                    # TODO: vendor term(s)
    rule: ""                    # TODO: how to compute from vendor term(s)
    confirmed: false

  HandleTime:
    acme: []                    # TODO: vendor term(s)
    rule: ""                    # TODO: how to compute from vendor term(s)
    trap: ""                    # TRAP: talk+hold semantics — confirm vendor talk metric EXCLUDES hold before adding
    confirmed: false
  ...
```

Every canonical field is present but empty. Your job in the next step is to
fill each one in.

---

## Step 3 — Fill in the dialect, one field at a time

For each canonical field in the dialect (start at the top, work down):

**3a — Read the canonical definition.** In `ontology/canonical_wfm.yaml`,
find the same field name. Read its `definition:` and `unit:`. Example:

```yaml
HandleTime:
  definition: "Handle time (talk + hold). Does not include ACW."
  unit: duration_seconds
```

**3b — Find the vendor equivalent in the catalog.** In
`fixtures/vendor_catalogs/acme.yaml`, look for column(s) that mean the same
thing. Example (fictional Acme):

```yaml
fields:
  TalkTime: "Time the agent spent talking on the call, in seconds. Does not include hold."
  HoldTime: "Time the caller spent on hold, in seconds."
  WrapTime: "After-call wrap-up time, in seconds."
```

**3c — Look for the trap.** Read the vendor description carefully. Words to
scan for: `excludes`, `includes`, `does not include`, `in milliseconds`,
`combined`, `total`. In this example, `TalkTime` "Does not include hold" —
so you must ADD `HoldTime` to get NICE's `HandleTime`.

**3d — Fill in the stub.** Type in the right panel:

```yaml
HandleTime:
  acme: [TalkTime, HoldTime]
  rule: "TalkTime + HoldTime"
  trap: "Acme TalkTime EXCLUDES hold — must add HoldTime to match NICE HandleTime; do not add WrapTime (that is WorkTime)"
  confirmed: true
```

**3e — Save. Move to the next field.** Repeat for every field in the stub.

**Rules of thumb while filling in:**

- If a field maps 1-to-1 with no arithmetic (like `QueueValue: SkillGroupID`),
  no `trap:` line is needed. Just fill in `acme:`, `rule:`, and set
  `confirmed: true`.
- If the mapping is more than just a rename, there's probably a trap.
  Write it down.
- If you're not sure yet, leave `confirmed: false` and move on. Come back
  when you've checked the vendor docs.

**Time estimate for a mid-complexity vendor: 30-60 minutes of focused reading.**

---

## Step 4 — Look at the AI-proposed mappings

**You open:** `ontology/proposed/acme.queue.PROPOSED.yaml`

**What you see:**

```yaml
meta:
  vendor: Acme
  report: queue
  status: proposed
fields:
  QueueValue:      "SkillGroupID"
  HandleTime:      "TalkTime"                  # confidence: 0.75
  HoldTime:        "HoldTime"                  # confidence: 0.95
  WorkTime:        "WrapTime"                  # confidence: 0.90
  ...
```

**What you do:** Compare each line against the dialect you just wrote in Step 3.

- `HandleTime: TalkTime` — the AI missed the hold-time addition. Your dialect
  says the correct answer is `TalkTime + HoldTime`. **Edit the line in the
  proposed file** to match your dialect:
  ```yaml
  HandleTime:  "TalkTime + HoldTime"     # TalkTime excludes hold; add HoldTime
  ```
- `QueueValue: SkillGroupID` — matches your dialect. Leave it.
- Continue for every field.

**Save the corrected proposed file** when done. Repeat for `agentqueue`
and `agentsystem`.

---

## Step 5 — Verify against a real data sample (optional but recommended)

**You need**: a small CSV of real vendor data + a hand-crafted "golden" XML
that shows what the output SHOULD look like for that data. If you have both:

**You type:**

```bash
python src/verify_mapping.py ontology/proposed/acme.queue.PROPOSED.yaml \
    --data fixtures/samples/acme_sample.csv \
    --golden fixtures/golden/Q_acme_expected.xml
```

**What appears:**

```
[verify] running formulas on 3 sample rows...
[verify] output matches golden ✓
```

Or, if something is off:

```
[verify] FAIL at row 2:
  field=HandleTime  expected=180  got=140   (missing hold time?)
```

If you see FAIL, go back to the proposed file, fix the formula (referencing
your dialect), and re-run verify until it passes.

---

## Step 6 — Approve: promote to `ontology/mappings/`

**You type** (one file at a time):

```bash
cp ontology/proposed/acme.queue.PROPOSED.yaml ontology/mappings/acme.queue.map.yaml
```

**Then edit** `ontology/mappings/acme.queue.map.yaml`:

- Find the line `status: proposed`
- Change it to `status: approved`
- Save.

Repeat for `.agentqueue` and `.agentsystem`.

**Why this step is manual:** it's the human sign-off. There's no command
for it because approving a mapping is an act of taking responsibility — a
person is putting their name on "yes, this is correct."

---

## Step 7 — Run the engine on real data to produce the XML

**You type:**

```bash
python src/engine.py --vendor Acme --report queue \
    --data fixtures/samples/acme_sample.csv \
    --out output/acme_queue_output.xml
```

**What appears:**

```
[engine] loading ontology/mappings/acme.queue.map.yaml
[engine] processed 96 rows across 3 queues
[engine] wrote output/acme_queue_output.xml (DTD-valid ✓)
```

That XML file is what you ship to NICE WFM.

---

## Step 8 — Run the sensor as a final check

**You type:**

```bash
python src/sensor.py output/acme_queue_output.xml
```

**What appears (good outcome):**

```
[sensor] OK — no vocabulary drift in output/acme_queue_output.xml
```

**What appears (bad outcome):**

```
[sensor] line 47: VENDOR_LEAK: acdtime
[sensor] line 89: FORBIDDEN_TERM: HandledTime
```

If you see leaks, it means an Acme column name (like `TalkTime`) escaped
into the canonical XML. Go back to your mapping file — the formula for that
field is wrong. Fix it and re-run engine + sensor.

---

## Step 9 — Run pytest as the final gate

**You type:**

```bash
pytest -v
```

**What appears (good outcome):**

```
========================= 41 passed in 17.69s =========================
```

If any test fails, do not ship. Fix and re-run.

---

## Summary cheat-sheet

| Step | You type | What happens | Time |
| --- | --- | --- | --- |
| 1 | `./add_vendor.sh Acme <input>` | Catalog + dialect stub + proposed mappings all appear | 30-60s |
| 2 | (open files in editor) | Empty stub visible | 1 min |
| 3 | (edit dialect file) | You fill in each canonical field | 30-60 min |
| 4 | (edit proposed files) | You correct AI mistakes using your dialect | 15-30 min |
| 5 | `python src/verify_mapping.py ...` | Formulas checked against real data | 10s |
| 6 | `cp ... && edit status:` | Approved mapping in `ontology/mappings/` | 2 min |
| 7 | `python src/engine.py ...` | Real XML output produced | 5s |
| 8 | `python src/sensor.py <output>` | Drift check on the XML | 2s |
| 9 | `pytest -v` | Full test suite | 20s |

**Total wall-clock for a mid-complexity vendor: ~1-2 hours**, of which
90% is you reading and typing in Steps 3 and 4. Everything else is one-liners.

---

## What if I get stuck?

- **Stuck at Step 3 — I don't know what a canonical field means.** Read the
  `definition:` and `unit:` for that field in `ontology/canonical_wfm.yaml`.
  Every canonical field is defined there.
- **Stuck at Step 3 — I can't find the vendor equivalent.** Not every
  canonical field maps to every vendor. If your vendor doesn't emit a
  particular metric, leave the stub for that field empty and set
  `confirmed: false`. The AI proposal for that field will also be empty
  or low-confidence; skip it during Step 4 review.
- **Stuck at Step 5 — verify keeps failing.** Print the sample row and the
  expected golden row side by side. The mismatch tells you which field's
  formula is wrong.
- **Stuck at Step 8 — sensor keeps reporting a leak.** The vendor column
  name is in your engine output XML. Grep the XML for it, trace it back to
  which canonical field it came from, then look at that field's formula
  in `ontology/mappings/acme.<report>.map.yaml`.
