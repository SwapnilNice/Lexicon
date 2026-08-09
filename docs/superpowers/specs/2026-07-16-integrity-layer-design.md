# Lexicon — Integrity Layer (Design Spec)

**Date:** 2026-07-16
**Author:** Swapnil Zade (with Claude Code, brainstorming session)
**Companion doc:** `Lexicon_Integrity_Layer_Design.docx` (project root)
**Status:** Approved — ready for implementation planning

---

## 1. Purpose

Lexicon's mapping harness guarantees that once a vendor-to-canonical transformer is approved, it runs unattended and keeps producing correct XML. This spec adds an **Integrity Layer** that guarantees the data flowing *through* that correct transformer is complete and consistent, catching two production failure classes the existing checks cannot see:

- **Feature A — Completeness & Cause:** distinguishes a pipeline gap (missing/failed/partial extract) from a genuine drop in volume, so WFM never learns a false demand drop.
- **Feature B — Queue Identity Resolution:** detects when an ACD renumbers a queue (e.g. Avaya split `44` → `47`) and proposes stitching the history so WFM sees one continuous queue.

**Non-goal:** modifying the existing engine, transformers, or their outputs. This layer is strictly additive.

## 2. Scope decisions (from brainstorming)

| # | Decision | Rationale |
|---|---|---|
| Slice | Both A and B end-to-end for the hackathon demo | Complete Integrity Layer story in one pass |
| Data density | 30-min intervals, business hours 08:00–18:00, Mon–Fri | ~20 intervals/day × 22 weekdays = ~440 intervals — small enough to inspect, dense enough for baselines |
| File layout | One CSV per report per day (`fixtures/avaya_30d/YYYY-MM-DD/{queue,agentqueue,agentsystem}.csv`) | Mirrors real ACD batch delivery; "add day 31" = drop a new subfolder |
| Day-31 test | Two separate scenarios: `pipeline_gap/` and `queue_renumber/` | Each feature tested in isolation; unambiguous failure diagnosis |
| Feature A action | Emit interval as-is; record finding in `data_health.json` sidecar | Non-destructive; sidecar IS the annotation; obvious in demo |
| Feature B action | Always propose in `identity_events.json`; require human ratification | Matches Lexicon's existing propose → verify → approve pattern; auditable |
| Integration model | Separate CLI in `src/integrity/`; existing engine untouched | Zero risk to working transformers; all existing tests pass unchanged |

## 3. Architecture

### 3.1 Control flow

```
raw Avaya CSVs (day N)
    │
    ▼
existing engine (transform_queue.py, engine.py)   ── UNCHANGED ──
    │
    ▼
NICE XML (day N)                                   ── UNCHANGED (byte-identical) ──
    │
    ▼
━━━━━━ NEW ━━━━━━
integrity_pass CLI (src/integrity/run.py)
    reads:  raw CSVs (day N) + state/history/ + state/baselines/ + state/queue_registry/
    emits:  out/<day>/data_health.json, out/<day>/identity_events.json
    updates: state/history/ (rolling append + prune > 30d), state/baselines/ (regenerate)
━━━━━━━━━━━━━━━━━━
```

### 3.2 Directory layout

```
src/integrity/
  __init__.py
  run.py                  # CLI: python -m src.integrity.run <day-folder>
  canonical.py            # Reuses engine's mapping to derive canonical records
  history_store.py        # Read/append/prune state/history/*.jsonl
  baseline.py             # Derive & load state/baselines/*.yaml
  registry.py             # Load/update state/queue_registry/*.yaml + ratify CLI
  completeness.py         # Feature A logic
  identity.py             # Feature B logic (fingerprint + match)
  sidecar.py              # data_health.json + identity_events.json writers

state/                    # gitignored except sample; per-customer scoping
  history/<customer>/queue.jsonl
                     agent_queue.jsonl
                     agent_system.jsonl
  baselines/<customer>/queue_baselines.yaml
  queue_registry/<customer>.yaml

fixtures/avaya_30d/
  2025-06-02/queue.csv agentqueue.csv agentsystem.csv
  …
  2025-07-11/…            # 22 weekdays, business hours only

fixtures/avaya_30d_scenarios/
  pipeline_gap/queue.csv agentqueue.csv agentsystem.csv
  queue_renumber/queue.csv agentqueue.csv agentsystem.csv

scripts/gen_avaya_30d.py  # deterministic synthetic data generator

tests/
  test_integrity_isolation.py
  test_completeness.py
  test_identity.py
  test_history.py
  test_demo_e2e.py
```

### 3.3 Isolation guarantees

- **Zero edits** to `src/engine.py`, `src/transform_queue.py`, or any file under `tests/` that predates this spec.
- `src/integrity/canonical.py` **imports the engine's mapping application as a library** — reuses formulas, does not reimplement them.
- `state/` is opt-in: if you never run integrity, nothing in the current pipeline changes.
- A regression test asserts XML bytes are byte-identical after the layer is present in the tree.

## 4. Data model

### 4.1 Canonical record (History Store)

Small, numeric, vendor-neutral. One row per `(customer, day, interval, canonical entity)`. Stored as JSONL for append-friendliness and human readability.

```jsonl
# state/history/<customer>/queue.jsonl
{"day":"2025-06-02","interval":"09:00","queue":"44","ContactsReceived":48,"HandledLong":40,"AbandonedLong":3,"HandleTime":3120,"HoldTime":240,"WorkTime":600,"ContactsActive":1}

# state/history/<customer>/agent_queue.jsonl
{"day":"2025-06-02","interval":"09:00","queue":"44","agent":"30128","Handled":10,"HandleTime":120}

# state/history/<customer>/agent_system.jsonl
{"day":"2025-06-02","interval":"09:00","agent":"30128","LoginTime":900,"ReadyTime":300,"NotReadyTime":90,"InternalContacts":1,"InternalHandleTime":101}
```

Fields obey `ontology/canonical_wfm.yaml` and `guides/inferential/QUEUE_glossary.md`. **No vendor terms** (`acdtime`, `holdtime`, `acwtime`, `split`, `logid`, etc.) appear in the store — a test enforces this.

**Retention:** append on ingest; prune anything older than 30 days on each run.

### 4.2 Baseline profiles

Regenerated from history each run. Encodes the intraday curve × weekday.

```yaml
# state/baselines/<customer>/queue_baselines.yaml
version: 1
generated_from_days: 30
queues:
  "44":
    weekday_slot:
      MON:
        "09:00": {expected_contacts: 46, std: 6, expected_handled: 39, expected_handletime_avg: 78}
        "09:30": {expected_contacts: 52, std: 7, ...}
```

Slots that are consistently zero across history simply don't appear — they never trigger.

### 4.3 Queue registry (Feature B)

```yaml
# state/queue_registry/<customer>.yaml
version: 1
queues:
  - canonical_id: Q-SALES
    aliases: ["44"]
    fingerprint:
      volume_by_slot:                  # normalized curve, sum = 1
        MON: {"09:00": 0.05, "09:30": 0.06, ...}
      operating_hours: ["08:00", "18:00"]
      agent_set: ["30128", "30143", "30157"]
      metadata: {name: "Sales", source_last_seen: "2025-07-11"}
    last_seen: "2025-07-11"
```

Feature B proposals do **not** mutate this file — ratification does, via the `registry approve` CLI.

## 5. Feature A — Completeness & Cause

For each `(queue, interval)` in the current day:

1. **Baseline lookup.** If no entry or `expected_contacts < 3` → naturally quiet → skip.
2. **Volume check.** If `observed >= expected − 3·std` → normal, no flag.
3. **Classify (first hit wins):**

   | Signal | Classification |
   |---|---|
   | All queues in the same interval collapse to ~0 | `whole_feed_failure` |
   | Agent-System shows staffed & ready agents but Queue shows ~0 handled | `queue_extract_gap` (the doc's headline signal) |
   | Job telemetry says extract errored / 0 rows (optional) | `extract_job_error` |
   | Source is genuinely low; agents not staffed | `genuine_drop` (pass through, no flag) |

4. **Emit finding** to `data_health.json` (Section 7.1).
5. **Do NOT modify XML.** The sidecar IS the annotation.

**Cold-start.** Baselines require ≥ 5 weekdays of history. Below that, steps 1–2 are skipped, but the **cross-report `queue_extract_gap` check still runs** — it needs only the current interval's three feeds. Matches the doc's promise that this signal "works from day one."

## 6. Feature B — Queue Identity Resolution

Runs after the current day's history append, before pruning.

1. **Disappearance.** For each `alias V` in the registry: if `V` has been absent for ≥ 3 consecutive weekday business-hours intervals in its normal operating window → flag `disappeared`. Tolerates 1–2 empty intervals so Feature A catches those as gaps rather than renumbers.
2. **Appearance.** Any vendor key in today's canonical records not in any `aliases` list → `unseen_key`, with a provisional fingerprint from today alone.
3. **Score each (disappeared, unseen_key) pair, 0–1:**

   | Component | Weight | Formula |
   |---|---|---|
   | Agent-set overlap | 0.50 | Jaccard(disappeared.agent_set, unseen_key.agent_set) |
   | Volume-by-slot shape | 0.25 | 1 − normalized L1 distance between renormalized curves |
   | Operating-hours overlap | 0.15 | overlap / union |
   | Metadata name similarity | 0.10 | token-set ratio if name present, else 0 |

   Threshold for **proposal**: score ≥ **0.60** (tunable).

4. **Emit proposal** to `identity_events.json` (Section 7.2). Never auto-apply.

5. **Ratification (separate CLI):**
   ```
   python -m src.integrity.registry approve out/<day>/identity_events.json \
       --proposal <id> --customer <c> --state-dir state
   ```
   Appends new alias to the matched `canonical_id`. Future days see the new key rolled into the existing canonical queue in the History Store.

**Edge cases:**
- **Multi-candidate conflict** — both proposals emitted with cross-referenced `conflicts_with` fields; human picks one.
- **Truly new queue** — no match found → recorded under `new_queues` (informational; no action).
- **Queue re-appears within the 3-interval window** — no proposal; Feature A already told the story.

## 7. Sidecar schemas

### 7.1 `data_health.json`

```json
{
  "schema_version": "1.0",
  "run_date": "2025-07-14",
  "customer": "demo",
  "generated_at": "2026-07-16T14:30:00Z",
  "summary": {
    "intervals_checked": 20,
    "findings_count": 1,
    "cold_start": false,
    "baseline_days_available": 22
  },
  "findings": [
    {
      "id": "F-2025-07-14-0930-44",
      "interval": "09:30",
      "queue": "44",
      "classification": "queue_extract_gap",
      "severity": "high",
      "expected_contacts": 46,
      "observed_contacts": 0,
      "z_score": -7.6,
      "evidence": {
        "agents_staffed": ["30128","30143","30157"],
        "ready_time_seconds_total": 890,
        "agent_system_handled": 0,
        "queue_handled": 0
      },
      "action_taken": "emit_with_annotation",
      "operator_note": null
    }
  ]
}
```

Valid `classification`: `queue_extract_gap`, `whole_feed_failure`, `extract_job_error`, `low_volume_no_signal`.

### 7.2 `identity_events.json`

```json
{
  "schema_version": "1.0",
  "run_date": "2025-07-14",
  "customer": "demo",
  "generated_at": "2026-07-16T14:30:00Z",
  "summary": {
    "proposals_count": 1,
    "new_queues_registered": 0,
    "disappeared_unmatched": 0
  },
  "proposals": [
    {
      "id": "P-2025-07-14-RENAME-0",
      "kind": "queue_renumber_merge",
      "disappeared_key": "44",
      "new_key": "47",
      "canonical_id": "Q-SALES",
      "confidence": 0.87,
      "score_breakdown": {
        "agent_overlap": 1.0,
        "volume_shape": 0.72,
        "hours_overlap": 1.0,
        "metadata": 0.0
      },
      "evidence": {
        "shared_agents": ["30128","30143","30157"],
        "disappeared_last_seen": "2025-07-10",
        "new_key_first_seen": "2025-07-14"
      },
      "recommended_action": "propose_alias",
      "status": "pending_review",
      "conflicts_with": []
    }
  ],
  "new_queues": [],
  "unmatched_disappearances": []
}
```

## 8. CLI surface

**Run integrity on a day:**
```
python -m src.integrity.run fixtures/avaya_30d_scenarios/pipeline_gap \
    --customer demo --state-dir state --out out/2025-07-14
```

**Warm history from 30 known-good days (skips A/B checks):**
```
python -m src.integrity.run fixtures/avaya_30d --customer demo --state-dir state --warmup
```

**Ratify a Feature B proposal:**
```
python -m src.integrity.registry approve out/2025-07-14/identity_events.json \
    --proposal P-2025-07-14-RENAME-0 --customer demo --state-dir state
```

**Inspect state (demo aid):**
```
python -m src.integrity.registry show --customer demo --state-dir state
python -m src.integrity.baseline show --queue 44 --customer demo --state-dir state
```

**Existing commands — unchanged:**
```
python src/transform_queue.py fixtures/avaya_30d/2025-06-02/queue.csv > out.xml
python src/sensor.py out.xml
pytest -v
```

## 9. Synthetic data generator

**Location:** `scripts/gen_avaya_30d.py` (outside `src/` — obviously a fixture builder).

**Fleet:**

| Split | Name | Agents (logids) | Volume shape |
|---|---|---|---|
| 44 | Sales | 30128, 30143, 30157 | Bell curve peaking 11:00–14:00, ~50 contacts at peak |
| 13 | Support | 30201, 30215 | Flatter ~22 contacts, small lunch dip |

**Determinism:** seeded RNG (default `--seed 42`); per-interval values = `round(base_curve[hh:mm] · weekday_factor[dow] · (1 + N(0, 0.08)))`; weekday factor Mon 1.05, Tue–Thu 1.00, Fri 0.90.

**Derivations obey the QUEUE glossary:**
- `acdtime = contacts · sampled_talk_avg` (N(60s, 10s))
- `holdtime = contacts · sampled_hold_avg` (N(8s, 3s), floor 0)
- `acwtime = contacts · sampled_acw_avg` — **never included in HandleTime**
- `abncalls ~ Poisson(0.05 · contacts)`, `acceptable = handled − abandoned_short`
- Agent-Queue rows split each queue across its logids by a stable per-agent share
- Agent-System rows sum Agent-Queue handling across queues; `i_availtime = interval_seconds − acdtime − ti_auxtime`

**CLI:**
```
python scripts/gen_avaya_30d.py \
    --start 2025-06-02 --days 30 --weekdays-only \
    --interval-min 30 --hours 08:00-18:00 --seed 42 \
    --out fixtures/avaya_30d

python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --scenario pipeline_gap --gap-interval 09:30 --gap-split 44 \
    --out fixtures/avaya_30d_scenarios/pipeline_gap

python scripts/gen_avaya_30d.py --day 2025-07-14 --seed 42 \
    --scenario queue_renumber --old-split 44 --new-split 47 \
    --out fixtures/avaya_30d_scenarios/queue_renumber
```

## 10. Testing plan

### 10.1 Regression fence

- `pytest -v` — every pre-existing test passes unchanged; no test file gets edited.
- `tests/test_integrity_isolation.py` — asserts engine output bytes match `fixtures/golden/*.expected.xml` after the layer is added.
- Sensor is exercised on any XML the layer touches; must report zero drift.

### 10.2 Feature A (`tests/test_completeness.py`)

| Test | Setup | Expected |
|---|---|---|
| `test_cross_report_gap_flagged_day_one` | Empty history + `pipeline_gap` scenario | Finding with `classification=queue_extract_gap`, evidence lists 3 staffed agents |
| `test_healthy_day_produces_no_findings` | Warm history + healthy day | `findings_count == 0` |
| `test_naturally_quiet_slot_not_flagged` | Warm history + synthetic day with 0 contacts at 08:00 | No finding |
| `test_whole_feed_failure` | Zero out entire `queue.csv` for one interval | `classification=whole_feed_failure`, all affected queues listed |
| `test_genuine_drop_not_flagged` | Queue low + no agents staffed | No finding — layer stays silent |

### 10.3 Feature B (`tests/test_identity.py`)

| Test | Setup | Expected |
|---|---|---|
| `test_queue_renumber_proposal` | Warm history + `queue_renumber` scenario | Proposal `44 → 47`, `Q-SALES`, agent_overlap=1.0, confidence ≥ 0.60 |
| `test_no_proposal_below_threshold` | New queue with completely different agents | No merge; recorded under `new_queues` |
| `test_ratify_appends_alias` | Run `registry approve` on the first test's proposal | `Q-SALES.aliases` now contains `47` |
| `test_ratified_alias_carries_history_forward` | Run integrity again on a day where only 47 appears | No new proposal; Feature A treats 47 as `Q-SALES` for baseline lookup |
| `test_ambiguous_conflict_flagged` | Two disappeared queues both match one new key | Both proposals emitted with `conflicts_with` cross-refs |

### 10.4 History store & baseline (`tests/test_history.py`)

- `test_append_and_prune` — 31 days appended, oldest is pruned.
- `test_baseline_regenerates_from_history` — post-warmup, `queue_baselines.yaml` reflects seeded curves within tolerance.
- `test_canonical_only_no_vendor_terms` — every JSONL row contains no `acdtime`, `holdtime`, `acwtime`, `split`, `logid`.

### 10.5 End-to-end demo (`tests/test_demo_e2e.py`)

Mirrors the exact demo flow:
1. Generate 30 days via `scripts/gen_avaya_30d.py`
2. Warmup: `python -m src.integrity.run fixtures/avaya_30d --warmup`
3. Run `pipeline_gap` scenario → assert expected `data_health.json` finding
4. Run `queue_renumber` scenario → assert expected `identity_events.json` proposal
5. Ratify → assert registry updated
6. Run existing `pytest` + `sensor` on XML — must stay clean

## 11. Out of scope for this slice

Deferred to production phase (§8.2 in the companion doc):
- Per-customer isolation controls beyond directory-per-customer.
- Backfill / re-request actions on Feature A findings.
- Extract-job telemetry integration.
- Approval UI for Feature B (CLI ratification suffices for the hackathon).
- Auto-apply thresholds for Feature B.
- Real-time / streaming operation (this design is batch, per-day).

## 12. Success criteria

The design is a success when, from a clean checkout:

1. `python scripts/gen_avaya_30d.py …` produces `fixtures/avaya_30d/` and the two scenario folders.
2. `python -m src.integrity.run fixtures/avaya_30d --warmup` populates `state/`.
3. Running integrity on `pipeline_gap` emits a `data_health.json` with exactly one `queue_extract_gap` finding whose evidence names the 3 staffed agents.
4. Running integrity on `queue_renumber` emits an `identity_events.json` proposal `44 → 47` with confidence ≥ 0.60.
5. `python -m src.integrity.registry approve …` mutates the registry as expected.
6. `pytest -v` is fully green — including all pre-existing tests.
7. `python src/sensor.py` on any XML touched by the layer reports zero drift.

If all seven hold, the Integrity Layer is ready to demo.
