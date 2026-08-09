# Lexicon — Avaya → NICE WFM Starter Kit

A working, minimal **Domain Context Harness** that turns **two different ACD
sources — Avaya CMS and Genesys Cloud — into the same NICE WFM Import History
XML** (Queue report). This is the Sparkathon proof-of-concept for Lexicon: one
canonical ontology, two vendor dialects, one enforceable gate.

The idea: a coding agent writes the Avaya→XML transformer, but it is *steered*
by an **inferential guide** (what to do) and *gated* by a **computational guide**
(deterministic tests), with a **sensor** watching for vocabulary drift.

**AI in the loop:** an auto-mapper *proposes* the vendor→canonical mapping; the
deterministic harness *verifies* it against a golden oracle; the human only
*approves* the flagged fields. AI proposes, harness verifies, human ratifies.
See `AUTOMAP.md`.

## What's here

```
ontology/
  canonical_wfm.yaml          # WHAT each WFM concept means (from the NICE spec) — source of truth
  avaya_cms_dialect.yaml      # Avaya CMS  -> canonical mapping + traps   (expert-authored)
  genesys_api_dialect.yaml    # Genesys Cloud -> canonical mapping + traps (expert-authored)
guides/inferential/
  QUEUE_glossary.md           # the guide the agent reads BEFORE coding
  QUEUE_cross_vendor.md       # same concept, two dialects — the HandleTime trap table
schema/
  HistPlugin.dtd              # structural validation (from the spec)
fixtures/
  avaya_queue_sample.csv                  # sample Avaya interval input (synthesized)
  genesys_queue_sample.json               # sample Genesys aggregate input (synthesized)
  golden/Q_060225.0900.expected.xml           # Avaya golden output (test oracle)
  golden/Q_060225.0900.genesys.expected.xml   # Genesys golden output (test oracle)
ontology/mappings/            # APPROVED executable maps: <vendor>.<report>.map.yaml
  avaya.queue.map.yaml  avaya.agentqueue.map.yaml  avaya.agentsystem.map.yaml
  genesys.queue.map.yaml  genesys.agentqueue.map.yaml  genesys.agentsystem.map.yaml
ontology/proposed/            # AI-PROPOSED maps land here (before expert approval)
fixtures/vendor_catalogs/
  avaya_hsplit_fields.yaml         # "discovered" vendor field catalog (input to the AI)
  genesys_conversation_metrics.yaml
src/
  engine.py                           # runs an executable .map.yaml -> NICE XML
  automap.py                          # AI PROPOSE step: catalog + ontology -> proposed map
  verify_mapping.py                   # grades a proposed map against the golden oracle
  transform_queue.py                  # CORRECT Avaya transformer (hand-written reference)
  transform_queue_genesys.py          # CORRECT Genesys transformer
  transform_queue_baseline_BUGGY.py   # naive no-Lexicon version (for the before/after)
  sensor.py                           # Ubiquitous Language Sensor (merges ALL vendor watchlists)
tests/
  test_contract_queue.py          # Avaya semantic + DTD contract tests
  test_contract_queue_genesys.py  # Genesys tests incl. ms->s and ACW-exclusion
  test_engine_and_automap.py      # engine reproduces goldens; propose->verify catches AI errors
CLAUDE.md                     # wiring: tells the coding agent to read the guide first
DEMO_RUNBOOK.md               # exact steps to run the before/after on stage
requirements.txt
```

## Quick start

```bash
pip install -r requirements.txt

# generate canonical XML from Avaya CSV
python src/transform_queue.py fixtures/avaya_queue_sample.csv > out.xml

# run the computational guide (semantic + DTD contract tests)
pytest -v

# run the sensor against any output or source file
python src/sensor.py out.xml
```

## Discover a new vendor's fields

`discover.py` turns a vendor's documentation (or a real data export) into a
field catalog YAML — the input the auto-mapper reasons over.

```bash
# From a real data export (no LLM needed, uses the header row):
python src/discover.py Acme --from-csv path/to/acme_export.csv

# From a single vendor doc (file or URL):
python src/discover.py Acme --doc path/to/acme_fields.pdf --engine llm

# Crawl a vendor's public documentation site from a seed URL:
python src/discover.py Acme --crawl https://docs.acme.com/wfm/fields --engine llm
```

Crawl mode stays on the seed URL's host, honors `robots.txt`, and caches every
fetched page under `fixtures/vendor_docs/<vendor>/` (gitignored). Bounds:
`--max-depth 2 --max-pages 30` by default; pass `--refresh` to re-fetch.

## How the three Lexicon components map to files

| Lexicon component | This kit |
|-------------------|----------|
| Canonical ontology (source of truth) | `ontology/canonical_wfm.yaml` |
| Vendor dialect map (expert layer) | `ontology/avaya_cms_dialect.yaml` |
| Inferential guide (feedforward) | `guides/inferential/QUEUE_glossary.md` + `CLAUDE.md` |
| Computational guide (gate) | `schema/HistPlugin.dtd` + `tests/test_contract_queue.py` |
| Ubiquitous Language Sensor (feedback) | `src/sensor.py` |

## The trap this proves (now across TWO vendors)

`HandleTime` in NICE WFM = **talk + hold** (after-call work is separate → `WorkTime`).
The same target field maps *oppositely* per vendor:

- **Avaya CMS:** `HandleTime = ACDTIME + ACDHOLDTIME` — must **not add** `ACWTIME`.
- **Genesys Cloud:** `HandleTime = (tTalk + tHeld)/1000` — `tHandle` already
  **includes** ACW *and* is in **milliseconds**, so mapping it straight across is
  wrong twice over.

A generic agent maps each vendor's own "handle time" field straight across and is
wrong in both — for opposite reasons. The ontology is the only thing that knows
the true target. See `guides/inferential/QUEUE_cross_vendor.md`.

## Scope & next steps

- **In scope now:** all three interval reports — Queue, Agent-Queue, Agent-System —
  end-to-end for both vendors (executable map + fixture + golden + tests). Adding a
  vendor produces all three mapping files via `./add_vendor.sh <Vendor> <catalog>`.
- **Next:** replicate the pattern for Agent-Queue and Agent-System (ontology
  entries already included), then swap synthesized fixtures for a real anonymized
  CMS extract, and add a held-out skill/VDN for non-circular evaluation.
- Avaya mappings are **verified against the CMS R21 manual** (`confirmed: true`)
  for the core fields; the few `confirmed: false` items are modelling choices
  you sign off: abandon short/long split (`slvlabns`), `ContactsActive` derivation,
  and Agent-System aggregation across splits (`ti_auxtime` vs per-split `i_auxtime`).
- Genesys metric names are best-effort (docs are JS-rendered) — confirm `tAnswer`
  and the within-SL count source against a real aggregate response.
- Fixtures use the real Avaya `hsplit` column names and real split numbers (44, 13).

> Stack note: Python/pytest was chosen for speed; the ontology, dialect map,
> guide, DTD, and fixtures are language-neutral. Only the transformer and tests
> would change if you target Java or C#.
