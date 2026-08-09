# The Lexicon Integrity Layer — Plain-English Explainer

> A companion to `Lexicon_Integrity_Layer_Design.docx` (the design brief) and
> `docs/superpowers/specs/2026-07-16-integrity-layer-design.md` (the technical spec).
> This document exists to answer "what does the layer actually do at runtime,
> and what am I looking at when the UI says '22 healthy days' and 'Registry entries'?"

---

## 1. The problem in one paragraph

The existing Lexicon transformer is *correct* — it faithfully turns an Avaya CSV
into the NICE Import History XML. But a correct transformer cannot tell the
difference between:

- **"The ACD had a quiet 09:30 slot"** — no calls, business-as-usual.
- **"Someone's extract job broke and no rows arrived for 09:30"** — a pipeline failure.

Both cases produce a valid, empty interval in the output. WFM cannot tell them
apart either — it only sees the file that arrives. If a pipeline gap slips
through, WFM learns "demand dropped to zero" and its forecast is quietly poisoned.

The Integrity Layer sits **between the transformer and WFM**. It keeps a rolling
history of past canonical intervals and uses that history to answer the question
the transformer cannot see: *"Is this empty interval real, or is it a gap?"*

It also answers a second question the transformer cannot see: *"When a new vendor
key appears (Avaya split 47) and an old one goes quiet (split 44), are they the
same logical queue with a new name?"*

---

## 2. Pipeline placement

```
raw Avaya CSVs (day N)
    |
    v
existing engine + approved mapping           <-- unchanged
    |
    v
NICE Import History XML (day N)              <-- unchanged, byte-identical
    |
    v
===== NEW =====
Integrity Pass  (src/integrity/run.py)
   reads:  raw CSVs + state/history + state/baselines + state/queue_registry
   writes: out/<day>/data_health.json           (Feature A findings)
           out/<day>/identity_events.json       (Feature B proposals)
   updates: state/history        (append this day, prune > 30 days)
            state/baselines      (regenerated from history)
===============
    |
    v
NICE WFM
```

The layer never touches the XML the engine produced. It is strictly additive.
A regression test (`tests/test_integrity_isolation.py`) proves the engine's
XML output stays byte-identical after the layer is added to the tree.

---

## 3. What "22 healthy days" means — the History Store

When the UI shows **State present · 22 days in history**, it is telling you:

> *The History Store currently holds 22 days of past canonical intervals for this customer.*

### What's in a "day"

Each day is one weekday (Mon–Fri), 20 intervals per day (08:00–18:00 in 30-minute
slots), with data for two queues (Avaya splits 44 "Sales" and 13 "Support") and
five agents. That's `22 × 20 = 440` intervals of history per queue.

The data was produced by `scripts/gen_avaya_30d.py` — deterministic synthetic
Avaya CSVs that mimic realistic behaviour: Sales peaks 11:00–14:00 at ~50 contacts
per interval, Support is flatter at ~22, the same five agents work the same two
queues day after day, with small day-to-day noise from a seeded RNG.

### Where it lives on disk

```
state/history/demo/
  queue.jsonl          # 880 canonical rows  (22 days × 20 intervals × 2 queues)
  agent_queue.jsonl    # 2200 rows          (22 × 20 × 5 agent-queue pairs)
  agent_system.jsonl   # 2200 rows          (22 × 20 × 5 agents)
```

### Why "canonical" matters

Every row in these files uses **canonical field names only**: `QueueValue`,
`ContactsReceived`, `HandledLong`, `HandleTime`, `AgentValue`, `LoginTime`,
`ReadyTime`, etc. Vendor-specific column names — Avaya's `acdtime`, `holdtime`,
`split`, `logid` — never appear. A test enforces this. That is what makes the
layer vendor-neutral: the same code will handle Genesys or Cisco once their
mappings are approved.

### Retention

The store keeps the most recent 30 days. When the layer processes day 31, it
appends day 31 and prunes anything older than 30 days back. That window is long
enough to cover four weekdays' worth of each weekday-slot combination — enough
to build a stable baseline.

### The baseline — derived from these 22 days

Every time the layer runs, it re-reads the history and recomputes a **baseline
profile**: for every `(queue, weekday, interval)` combination, it stores the
expected value and standard deviation of `ContactsReceived`.

```yaml
# state/baselines/demo/queue_baselines.yaml (excerpt)
queues:
  "44":
    weekday_slot:
      MON:
        "09:30":
          expected_contacts: 60
          std: 2
          expected_handled: 55
          expected_handletime_avg: 66
          sample_count: 5
```

**Slots that are consistently zero across history do not appear.** Weekends,
overnight, before 08:00 — none of them get baseline entries, so they can never
trigger a false gap alert.

**Cold-start rule:** baseline needs at least 5 weekdays of history to be
trusted. Below that, the "expected vs observed" check is skipped, but the
**cross-report contradiction check still runs** — see §5.

---

## 4. What "Registry entries" means

The **queue registry** answers a completely different question from the
history/baseline: *"Which vendor keys are the same logical queue?"*

Every registry entry is one canonical queue identity. It has three parts:

### Aliases

The list of **vendor keys** that currently point at this identity.

```yaml
- canonical_id: Q-44
  aliases: ["44"]
```

`aliases: ["44"]` says "Avaya split 44 IS the Sales queue." If the ACD
renumbers Sales to split 47 tomorrow, and you approve the merge proposal, the
entry becomes:

```yaml
- canonical_id: Q-44
  aliases: ["44", "47"]
```

From that moment on, WFM sees one continuous Sales queue — no discontinuity
between day 30 and day 31.

### Fingerprint

A behavioural signature built from history. The registry uses it to score
"is queue X the same as queue Y?" when a rename is suspected.

```yaml
fingerprint:
  agent_set: ["30128", "30143", "30157"]     # the Sales team
  operating_hours: ["08:00", "08:30", ..., "17:30"]
  volume_by_slot:
    MON: {"08:00": 0.02, "08:30": 0.04, "09:00": 0.05, ...}   # sums to 1.0 per weekday
  metadata: {name: null, source_last_seen: "2025-07-01"}
```

The most powerful component is `agent_set`. The same agents rarely move
wholesale to a genuinely new queue, so if split 47's agent set matches split 44's
exactly, "renamed" is by far the best explanation.

### last_seen

The most recent day this queue appeared in the history. When a queue disappears
for several intervals, its `last_seen` doesn't advance — that is how Feature B
knows a "disappearance" happened.

### Where it lives

```
state/queue_registry/demo.yaml
```

One YAML file per customer. Rebuilt on every warmup, but **aliases are preserved**
across rebuilds — that is how a human-approved merge survives.

---

## 5. The two features, in plain terms

Both features run every time the Integrity Pass processes a day.

### Feature A — Completeness & Cause

**Question:** For each interval that arrived, is what we see plausible?

**Priority-ordered classification** — first match wins:

| Signal | Classification | Meaning |
|---|---|---|
| **No queue rows at all this interval, but agents were staffed and ready** | `whole_feed_failure` | The entire queue extract failed. Every queue lost visibility at once. |
| **Baseline says busy, but we got zero — AND Agent-System says agents were staffed and ready** | `queue_extract_gap` | This specific queue's extract dropped. WFM must not learn "demand went to zero." |
| **Baseline says busy, we got low — AND no agents staffed** | *(silent — genuine drop)* | The source really was low; agents were on break or off. WFM handles this normally. |
| **No matching baseline entry** | *(silent — naturally quiet slot)* | Weekend, overnight, before opening. Never triggers. |

**Cold start (< 5 weekdays of history):** the baseline-driven checks are skipped,
but the `queue_extract_gap` check still fires purely from the current interval's
three feeds (queue.csv shows nothing, agent-system shows staffed & ready → gap).

**The result** goes to `out/<day>/data_health.json`. The XML is never touched —
that is the "don't disturb the working model" guarantee.

### Feature B — Queue Identity Resolution

**Question:** Has a queue been renamed? Are any of the vendor keys I don't
recognise actually familiar queues under a new number?

**Steps:**

1. **Disappearance detection.** For each vendor key in the registry: has it
   been absent from history for 3+ consecutive intervals in its normal window?
   → `disappeared_key`.

2. **Appearance detection.** For each vendor key in *today's* data that is not
   in any `aliases` list: → `unseen_key`. Build a provisional fingerprint from
   today's data alone.

3. **Scoring.** For every `(disappeared_key, unseen_key)` pair, compute a
   0.0–1.0 match score:

   | Component | Weight | How |
   |---|---|---|
   | Agent-set overlap | 0.50 | Jaccard(disappeared.agent_set, unseen_key.agent_set) |
   | Volume-by-slot shape | 0.25 | 1 − normalised L1 distance between the two curves |
   | Operating-hours overlap | 0.15 | overlap ÷ union |
   | Metadata name similarity | 0.10 | token-set ratio, if names present |

4. **Propose.** If score ≥ 0.60 → write a proposal to
   `out/<day>/identity_events.json` with `status: pending_review`.
   **Never auto-apply.** The alias is only added after you (or an operator) runs:

   ```
   python -m src.integrity.registry approve out/<day>/identity_events.json \
       --proposal <id> --customer <c> --state-dir state
   ```

5. **Truly new queues.** If an unseen key doesn't match any disappeared key
   above threshold, it is recorded under `new_queues` — informational, no action.

---

## 6. A concrete run (the demo)

State is warmed from `fixtures/avaya_30d/`: 22 days, both queues profiled,
registry seeded with `Q-44` (alias: 44) and `Q-13` (alias: 13).

### Scenario 1 — pipeline_gap/2025-07-14

The synthetic generator produces a normal day *except* that queue 44's row for
09:30 is missing from `queue.csv`. `agentsystem.csv` still shows all 5 agents
staffed and ready at 09:30. This is exactly what a partial extract failure
looks like on the wire.

Run:

```
python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/pipeline_gap/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14
```

Output — `out/2025-07-14/data_health.json`:

```
findings: 1
  queue_extract_gap @ 09:30  queue=44
    expected_contacts: 60      (from baseline)
    observed_contacts: 0
    z_score: -30.0
    evidence:
      agents_staffed: [30128, 30143, 30157, 30201, 30215]
      ready_time_seconds_total: 4260
      agent_system_handled: 0
      queue_handled: 0
```

The finding tells the story: baseline said 60, we got 0, z = -30 standard
deviations, and — the decisive part — five agents were staffed and ready. This
was not a real drop.

### Scenario 2 — queue_renumber/2025-07-14

The same day, but split 44 has been renamed to split 47 across all three CSVs.
The three Sales agents are still handling the calls. Warm state on the healthy
22 days first, then run:

```
python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/queue_renumber/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14
```

Output — `out/2025-07-14/identity_events.json`:

```
proposals: 1
  P-2025-07-14-RENAME-0:
    disappeared_key: 44
    new_key:         47
    canonical_id:    Q-44
    confidence:      0.80
    score_breakdown: {agent_overlap: 1.0, volume_shape: 0.59, hours_overlap: 1.0, metadata: 0.0}
    evidence:
      shared_agents: [30128, 30143, 30157]
      disappeared_last_seen: 2025-07-01
      new_key_first_seen:    2025-07-14
```

Ratify:

```
python -m src.integrity.registry approve out/2025-07-14/identity_events.json \
    --proposal P-2025-07-14-RENAME-0 --customer demo --state-dir state
```

The registry entry for `Q-44` now has `aliases: [44, 47]`. Future days that
see split 47 will roll straight into `Q-44`'s history in the store — WFM sees
one continuous queue.

**Note on double-signal.** Feature A will *also* fire many findings on the
queue_renumber day (queue 44's baseline says busy, we got zero across every
interval). That's honest: A says "queue 44 vanished," B proposes "47 is queue
44." A human ratifies B and A stops firing next day. The layer never
auto-decides between them.

---

## 7. The UI, mapped to the concepts above

The Integrity Layer page (`src/ui/pages/2_Integrity_Layer.py`) is a thin
wrapper around the CLI. Every button maps to a subprocess call:

| UI element | What it does under the hood |
|---|---|
| **Warmup** button | `python -m src.integrity.run --warmup --input fixtures/avaya_30d ...` |
| **Reset state** button | `rm -rf state/history/<customer> state/baselines/<customer> state/queue_registry/<customer>.yaml` |
| **Run integrity pass** button | `python -m src.integrity.run --input <folder> --out out/... --run-date ...` |
| **Ratify** button per proposal | `python -m src.integrity.registry approve ...` |
| **Data Health / Identity Events / Registry / Raw JSON tabs** | Render the sidecar JSONs / registry YAML from disk |

The metrics strip at the top translates directly:

- **State present · 22 days in history** — the History Store has 22 canonical days for this customer.
- **Baseline: 22 days · 2 queues profiled** — the baseline YAML was regenerated from those 22 days and covers 2 queues.
- **Registry entries: 2** — two canonical queue identities exist (`Q-44`, `Q-13`), each currently with one alias.
- **Findings (Feature A) = N** — how many suspect intervals A flagged on the last run.
- **Proposals (Feature B) = N** — how many queue-rename proposals B produced on the last run.
- **Cold start? = no** — history has ≥ 5 weekdays; baseline is trusted.

---

## 8. What the layer does *not* do

- **It does not modify the NICE XML.** All outputs are sidecar JSONs.
- **It does not auto-apply queue merges.** Every merge goes through human ratification.
- **It does not backfill missing intervals.** A future extension could; the current
  action is `emit_with_annotation` — the sidecar IS the annotation.
- **It does not replace WFM's forecasting.** WFM still handles business outliers.
  The layer catches *pipeline* anomalies WFM cannot see.
- **It does not touch the transformer or the sensor.** Regression tests prove
  the engine's output stays byte-identical.

---

## 9. Where things live — one-page reference

| Concept | On disk |
|---|---|
| Approved mapping (Avaya) | `ontology/mappings/avaya.*.map.yaml` |
| Canonical field definitions | `ontology/canonical_wfm.yaml` |
| Vendor traps + dialect | `ontology/avaya_cms_dialect.yaml` |
| Synthetic healthy fixture | `fixtures/avaya_30d/YYYY-MM-DD/{queue,agentqueue,agentsystem}.csv` |
| Synthetic scenarios | `fixtures/avaya_30d_scenarios/{pipeline_gap,queue_renumber}/2025-07-14/` |
| Data generator | `scripts/gen_avaya_30d.py` |
| **History store** | `state/history/<customer>/{queue,agent_queue,agent_system}.jsonl` |
| **Baseline profiles** | `state/baselines/<customer>/queue_baselines.yaml` |
| **Queue registry** | `state/queue_registry/<customer>.yaml` |
| **Feature A findings** | `out/<day>/data_health.json` |
| **Feature B proposals** | `out/<day>/identity_events.json` |
| Integrity CLI (run) | `python -m src.integrity.run` |
| Registry CLI (approve/show) | `python -m src.integrity.registry` |
| UI page | `src/ui/pages/2_Integrity_Layer.py` (in the Streamlit multi-page nav) |
| Tests | `tests/test_history.py`, `test_completeness.py`, `test_identity.py`, `test_registry.py`, `test_run_cli.py`, `test_integrity_isolation.py`, `test_demo_e2e.py` |

---

## 10. Try it in one minute

```bash
# 1. Warm state (22 days of healthy history)
rm -rf state/history state/baselines state/queue_registry
python -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state

# 2. Feature A — pipeline gap
python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/pipeline_gap/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14
cat out/2025-07-14/data_health.json | python -m json.tool

# 3. Feature B — queue renumber (needs a fresh state)
rm -rf state/history state/baselines state/queue_registry
python -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state
python -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/queue_renumber/2025-07-14 \
    --customer demo --state-dir state \
    --out out/2025-07-14 --run-date 2025-07-14
cat out/2025-07-14/identity_events.json | python -m json.tool

# 4. Ratify the proposal
python -m src.integrity.registry approve out/2025-07-14/identity_events.json \
    --proposal P-2025-07-14-RENAME-0 --customer demo --state-dir state

# 5. Confirm the alias landed
python -m src.integrity.registry show --customer demo --state-dir state

# 6. Regression fence — the engine's XML must still be byte-identical
pytest -v
```

If step 6 is green and step 5 shows `Q-44` with `aliases: [44, 47]`, the layer
is working end-to-end.
