# The AI loop — discover → propose → verify → approve

This is what makes Lexicon *AI in the driving seat* rather than static validation.
The AI does the expensive thinking (deriving the mapping); the deterministic
harness catches its mistakes; the human only ratifies.

## The four steps

**1. Discover** — read the vendor's docs/schema into a field catalog (name +
description). Examples: `fixtures/vendor_catalogs/avaya_hsplit_fields.yaml`,
`genesys_conversation_metrics.yaml`.

**2. Propose** — the auto-mapper reads the catalog + the canonical ontology and
proposes an executable mapping (a formula per canonical field):
```bash
python src/automap.py fixtures/vendor_catalogs/avaya_hsplit_fields.yaml --vendor Avaya
python src/automap.py fixtures/vendor_catalogs/genesys_conversation_metrics.yaml --vendor Genesys
```
Output lands in `ontology/proposed/<vendor>.queue.PROPOSED.yaml` with a
confidence + rationale per field. (Default engine is an offline heuristic so the
demo is reproducible; `--engine llm` uses a real model — see below.)

**3. Verify** — run the proposal through the engine against the golden oracle.
The harness reports exactly which fields are right and which the expert must fix:
```bash
python src/verify_mapping.py ontology/proposed/avaya.queue.PROPOSED.yaml \
    fixtures/avaya_queue_sample.csv fixtures/golden/Q_060225.0900.expected.xml
```

**4. Approve** — the expert fixes only the flagged formulas and promotes the file
to `ontology/mappings/<vendor>.queue.map.yaml` with `status: approved`. That
approved, executable map is the source of truth the engine and tests run on.

## What the demo shows (and why it's honest)

- **Avaya:** the AI gets the 1:1 fields right (QueueValue, HoldTime, WorkTime,
  QueueDelayTime, ContactsActive) and misses the ones needing arithmetic —
  `HandleTime` (it proposes `acdtime`, forgetting `+ holdtime`) and the
  service-level splits. The harness catches exactly those. **5 correct, 5 to fix.**
- **Genesys:** the AI proposes `tHandle_ms` for HandleTime (the trap — it includes
  ACW) and leaves everything in milliseconds. The harness catches all of it.
  **2 correct, 8 to fix** — the harness earns its keep more on the harder vendor.
- **The punchline:** on Genesys the AI reported **confidence 1.0 on a wrong field.**
  That is the whole thesis in one line: *don't trust the AI's confidence — verify.*
  The static harness is what makes the AI's proposals safe to use.

## Division of labour
- **AI** — discovery + proposing formulas (the expensive cognition).
- **Harness (deterministic)** — grading proposals + enforcing the approved map.
- **Human** — approve/correct only the flagged fields (minutes, not weeks).

## Using a real LLM (product path)
`--engine llm` builds a prompt from the catalog + ontology and calls a model
(`anthropic` SDK + `ANTHROPIC_API_KEY`). If neither is present it prints the exact
prompt it would send, so you can run it by hand. The verify + approve steps are
identical regardless of which engine produced the proposal — that's the point:
the trust comes from the harness, not from the model.
