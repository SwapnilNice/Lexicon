# How to fill in a dialect file — a walk-through with examples

This document answers one question in detail: **once `add_vendor.sh` has run and
scaffolded the dialect stub, what exactly do I type into it?**

## The vocabulary you need before we start

Three terms show up constantly. Get these straight and everything else follows.

- **Canonical field** — a NICE-WFM concept from `ontology/canonical_wfm.yaml`.
  Examples: `HandleTime`, `HoldTime`, `WorkTime`, `QueueValue`. These are
  vendor-neutral. They mean the same thing regardless of whether the data
  comes from Avaya, Genesys, or Cisco.

- **Vendor term** — a column name in the vendor's own schema. Examples:
  Avaya's `acdtime`, Genesys's `tHandle`, Cisco UCCE's `TalkTimeToHalf`. These
  live in `fixtures/vendor_catalogs/<vendor>.yaml` after discovery. They mean
  whatever the vendor's documentation says they mean — which is often subtly
  different from what NICE means by the same-sounding concept.

- **Trap** — the specific way a vendor term is *not* what a NICE canonical
  field expects. Example: Avaya's `acdtime` sounds like "the time spent talking
  on an ACD call" (which is what NICE `HandleTime` measures) but it EXCLUDES
  hold time. If you write `HandleTime = acdtime` you will silently under-count
  every interval, forever. The trap sentence is the sign that stops the next
  engineer from making that mistake.

## Anatomy of one field in the stub

After `add_vendor.sh Cisco_UCCE ...` runs, the file
`ontology/cisco_ucce_dialect.yaml` looks like this (for one field):

```yaml
queue:
  HandleTime:
    cisco_ucce: []            # TODO: vendor term(s)
    rule: ""                  # TODO: how to compute from vendor term(s)
    trap: ""                  # TRAP: talk+hold semantics — confirm vendor talk metric EXCLUDES hold before adding
    confirmed: false
```

Four keys. What each one means:

| Key | Purpose | Type | Who writes it |
| --- | --- | --- | --- |
| `cisco_ucce:` | The vendor column name(s) that supply this canonical field | list of strings | You |
| `rule:` | The arithmetic that turns those vendor columns into the canonical value | string | You |
| `trap:` | A human-readable warning about what makes this mapping non-obvious | string | You (if there is a trap) |
| `confirmed:` | Sign-off: have you verified this against the vendor's own docs? | true / false | You (flip to `true` once verified) |

The prefix key (`cisco_ucce:`) matches the vendor's short name — for Avaya it
would be `avaya:`, for Genesys it would be `genesys:`.

## Three worked examples — trivial, trap, unit-conversion

### Example 1 — a trivial mapping (no trap)

**Canonical field**: `QueueValue` — the queue identifier.

**Look in the catalog** (`fixtures/vendor_catalogs/cisco_ucce.yaml`):
```yaml
fields:
  SkillTargetID:  "Unique identifier for the skill group (queue)."
```

**Look in canonical_wfm.yaml**:
```yaml
QueueValue:
  definition: "Contact Router contact queue identifier (the queue key)."
  unit: key
```

Both agree: it's just a queue ID. No arithmetic, no unit conversion, no trap.

**Fill in the stub**:
```yaml
QueueValue:
  cisco_ucce: [SkillTargetID]
  rule: "SkillTargetID"
  confirmed: true
```

Notice: no `trap:` line (there is none), and `confirmed: true` because
you cross-checked the Cisco schema doc and it matches.

### Example 2 — a mapping with a trap (the classic Avaya case)

**Canonical field**: `HandleTime` — talk time + hold time.

**Look in the catalog** (`fixtures/vendor_catalogs/avaya_hsplit_fields.yaml`):
```yaml
fields:
  acdtime:   "Talk time of all ACD calls. Does not include hold time."
  holdtime:  "Time ACD callers spent on hold."
  acwtime:   "After-call work (wrap-up) time associated with ACD calls."
```

**Look in canonical_wfm.yaml**:
```yaml
HandleTime:
  definition: "Handle time = talk + hold. Does not include ACW."
  unit: duration_seconds
```

Now compare carefully:
- Avaya `acdtime` sounds like it means "handle time" but the description
  says **"does not include hold time"**.
- NICE `HandleTime` **does** include hold.
- Also: NICE `HandleTime` does **not** include ACW (`acwtime` is a separate
  concept — `WorkTime`).

**If you naively wrote `HandleTime: acdtime`, you would be wrong.** You'd
under-count by however much hold time occurred.

**Fill in the stub correctly**:
```yaml
HandleTime:
  avaya: [acdtime, holdtime]
  rule: "acdtime + holdtime"
  trap: "acdtime EXCLUDES hold time in Avaya's model, so hold must be added; never merge in acwtime (that is WorkTime)"
  confirmed: true
```

The `trap:` sentence is the whole reason this file exists. When someone
6 months from now sees `rule: "acdtime + holdtime"` and wonders "why the
addition?", the `trap:` explains it.

### Example 3 — a mapping with a unit conversion (Genesys)

**Canonical field**: `HandleTime` again, but for Genesys Cloud.

**Look in the catalog** (`fixtures/vendor_catalogs/genesys_conversation_metrics.yaml`):
```yaml
fields:
  tTalk:   "Total talk time for the conversation, in milliseconds."
  tHeld:   "Total time on hold, in milliseconds."
  tAcw:    "After-call work time, in milliseconds."
  tHandle: "Combined interaction time (talk + hold + ACW), in milliseconds."
```

**Look in canonical_wfm.yaml**:
```yaml
HandleTime:
  unit: duration_seconds       # <-- SECONDS, not milliseconds
```

Two traps stacked on top of each other:
1. Genesys `tHandle` sounds like it maps directly to NICE `HandleTime` — but
   Genesys `tHandle` **includes ACW**, and NICE `HandleTime` **excludes ACW**.
2. Genesys ships everything in **milliseconds**. NICE expects **seconds**.

Naive answer `HandleTime: tHandle` is wrong twice over: includes ACW, and is
1000× too large.

**Fill in the stub correctly**:
```yaml
HandleTime:
  genesys: [tTalk, tHeld]
  rule: "(tTalk + tHeld) / 1000"
  trap: "Genesys tHandle INCLUDES ACW — do NOT use it; must build from tTalk + tHeld only. All Genesys durations are in milliseconds; divide by 1000 to get seconds."
  confirmed: true
```

Two things captured in one trap sentence: the ACW inclusion, and the
milliseconds-to-seconds conversion.

## What "confirmed: true" means (and when to leave it false)

Flip `confirmed:` to `true` **only after you have**:

1. Read the vendor's own schema documentation (not just the catalog's
   one-line description — the catalog may be LLM-summarised and lossy).
2. Cross-checked the vendor's definition against `canonical_wfm.yaml`'s
   definition of the same canonical field.
3. Identified any unit differences, exclusion/inclusion quirks, or
   aggregation gotchas — and written them into `trap:`.

Leaving `confirmed: false` is fine — it means "the AI can propose a mapping
using this field, but the sensor and the reviewer know it hasn't been
signed off yet." Over time, all fields should reach `confirmed: true` or
be deliberately marked as unavailable.

## The catalog vs the dialect — which do I look at?

At authoring time, you have **both files open**:

- Open `fixtures/vendor_catalogs/<vendor>.yaml` on one side — this is
  the vendor's field inventory.
- Open `ontology/<vendor>_dialect.yaml` on the other side — this is the
  stub you're filling in.

You also have `ontology/canonical_wfm.yaml` open somewhere — it's your
reference for what each canonical field means and its unit.

Workflow per canonical field:
1. Read the canonical field's `definition` in `canonical_wfm.yaml`.
2. Find the vendor's equivalent column(s) in the catalog.
3. Read the vendor description carefully — look for words like "excludes",
   "includes", "in milliseconds", "does not include hold time".
4. Write the `<vendor>:` list, the `rule:` formula, and (if there's a
   quirk) the `trap:` sentence.
5. Set `confirmed: true`.

## How this connects to the rest of the pipeline

The dialect is **reference material**, not runtime code. It gets consumed by:

- **`src/sensor.py`** — reads the `drift_watchlist` block at the bottom
  of every dialect file, uses those vendor terms to detect leakage into
  NICE canonical output. This is automatic.
- **The human reviewer** — reads the trap fields when reviewing the
  AI-proposed mappings in `ontology/proposed/`, to catch cases where the
  AI proposed a naive mapping that walks into a known trap.

The engine (`src/engine.py`) does NOT read the dialect. It runs the
approved mapping files in `ontology/mappings/` directly. So the dialect
is an authoring-time and drift-checking artifact, not a runtime dependency.

## Common mistakes

- **Copying the vendor's field description verbatim into `rule:`**. `rule:`
  is a formula (executable arithmetic on vendor columns), not prose.
- **Leaving `trap:` empty when there IS a trap**. If the mapping is not
  literally `canonical: vendor_column_of_same_name`, there is probably a
  trap. Writing it down protects the next engineer.
- **Flipping `confirmed: true` based on the AI's catalog description alone.**
  The catalog description may be LLM-summarised; verify against the vendor's
  original schema doc.
- **Adding `acwtime` (or the vendor equivalent) into `HandleTime`.** ACW is
  `WorkTime` in NICE's model — separate concept. This is the #1 mistake.
