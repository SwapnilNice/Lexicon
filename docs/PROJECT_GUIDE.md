# Lexicon — Project Guide

A one-stop guide for running the project, understanding the flow, and adding a
new ACD vendor. This is a working companion to `README.md`, `AUTOMAP.md`, and
`CLAUDE.md` — read those for the *why*; read this for the *how*.

## Table of contents

1. [What Lexicon is (one paragraph)](#what-lexicon-is-one-paragraph)
2. [Architecture at a glance](#architecture-at-a-glance)
3. [How to run the project](#how-to-run-the-project)
4. [End-to-end flow (data + control)](#end-to-end-flow-data--control)
5. [Repository layout](#repository-layout)
6. [Adding a new ACD vendor — step by step](#adding-a-new-acd-vendor--step-by-step)
7. [Troubleshooting cheat-sheet](#troubleshooting-cheat-sheet)

---

## What Lexicon is (one paragraph)

Different call-center vendors (Avaya CMS, Genesys Cloud, …) emit contact-center
interval data with **the same concepts but different names, units, and traps**.
NICE WFM expects one canonical XML shape. Lexicon is a small harness that turns
each vendor's data into that canonical XML *reliably*, with three layers of
defence:

- an **inferential guide** (a glossary the AI reads before coding);
- a **computational guide** (deterministic tests + a DTD);
- a **sensor** that watches the output for vocabulary drift.

An AI agent **proposes** how vendor fields map to canonical fields; the harness
**verifies** the proposal against a golden oracle; a human only **approves** the
few fields the harness flagged. AI proposes → harness verifies → human ratifies.

---

## Architecture at a glance

### Top layer — two peer ontology files

```
┌────────────────────────────────────────┐        ┌────────────────────────────────────────┐
│      ontology/canonical_wfm.yaml       │        │     ontology/<vendor>_dialect.yaml     │
│   source of truth — WHAT things mean   │        │   expert layer — HOW vendor terms map  │
│   (unit-correct, vendor-neutral)       │        │   to canonical, plus TRAPS per field   │
│                                        │        │   (per-field confirmed: true/false)    │
└────────────────────────────────────────┘        └────────────────────────────────────────┘
        │                                                  ▲                    │       │
        │ reasoned over by                                 │ src/scaffold_      │       │
        │ every pipeline stage                             │ dialect.py         │       │
        │                                                  │ (stub from         │       │
        │                                                  │  catalog, then     │       │
        │                                                  │  hand-authored)    │       │
        │                                                  │                    │       │
        │                                                  │      reference for │       │ drift_watchlist
        │                                                  │      reviewer      │       │ read by sensor
        │                                                  │              (dashed arrows below)
        ▼                                                  │                    ▼       ▼
```

### Pipeline (solid arrows = data flow, dashed = reference)

```
┌──────────────┐  discover   ┌──────────────────────┐  propose    ┌──────────────────────────┐
│ vendor docs  │────────────▶│ fixtures/vendor_     │────────────▶│ ontology/proposed/       │
│ (URL/PDF/CSV)│ src/discover│ catalogs/<v>.yaml    │ src/automap │ <v>.<report>.PROPOSED    │
└──────────────┘             │  (field name+desc)   │             │       .yaml              │
                             └──────────┬───────────┘             └────────────┬─────────────┘
                                        │ scaffold_dialect                     │ verify
                                        ▼ (stubs the dialect above)            ▼
                                                             ┌──────────────────────────┐
                             ┌────────────────────────┐      │ src/verify_mapping.py    │
                             │ fixtures/*.csv/.json   │─────▶│ vs fixtures/golden/*.xml │
                             │ (real data)            │grade └────────────┬─────────────┘
                             └───────────┬────────────┘                   │ flagged fields
                                         │                                ▼
                                         │              dialect  ┌──────────────────────────┐
                                         │              ─ ─ ─ ─ ▶│ human expert reviews the │
                                         │              (as ref) │ few flagged formulas     │
                                         │                       └────────────┬─────────────┘
                                         ▼                                    │ approve
                             ┌────────────────────────┐                       ▼
                             │ src/engine.py          │          ┌──────────────────────────┐
                             │ (executes the .map)    │◀─────────│ ontology/mappings/       │
                             └───────────┬────────────┘          │ <v>.<report>.map.yaml    │
                                         │                       │  (status: approved)      │
                                         ▼                       └──────────────────────────┘
                             ┌────────────────────────┐
                             │ NICE WFM Import        │
                             │ History XML            │
                             └───────────┬────────────┘
                                         ▼
                             ┌────────────────────────┐  drift_watchlist merged from
                             │ src/sensor.py          │◀ ─ ─ ─every ontology/*_dialect.yaml
                             │ (vocabulary-drift gate)│      (vendor terms + forbidden names)
                             └────────────────────────┘
```

The dialect isn't in the linear pipeline — it's a **reference document** that (a) gets *scaffolded* from the catalog once, (b) is *consulted* by the human reviewer when a field is flagged, and (c) is *read* by the sensor to build its drift watchlist. That's why it lives at the top as a peer of `canonical_wfm.yaml` rather than as a stage in the flow.

Three roles for the moving pieces:

| Role | File(s) | What it does |
| --- | --- | --- |
| **Ontology (canonical truth)** | `ontology/canonical_wfm.yaml` | Defines every WFM concept once, unit-correct. |
| **Vendor dialect (expert layer)** | `ontology/<vendor>_*_dialect.yaml` | Human-authored translation table + trap notes for a vendor. |
| **Inferential guide (feedforward)** | `guides/inferential/*.md` + `CLAUDE.md` | What the AI reads *before* it writes code. |
| **Computational guide (gate)** | `schema/HistPlugin.dtd` + `tests/test_contract_queue*.py` | Deterministic pass/fail. |
| **Sensor (feedback)** | `src/sensor.py` | Watches output XML for vendor terms and unit slips. |
| **Discover → Propose → Verify → Approve pipeline** | `src/discover.py`, `src/automap.py`, `src/verify_mapping.py`, `src/engine.py` | The AI-in-the-loop assembly line. |

---

## How to run the project

### Prerequisites

- Python 3.10+ (uses `list[tuple[...]]` PEP 604 syntax in a few places)
- `pip install -r requirements.txt`
- Optional, only for `discover.py --engine llm`: `pip install anthropic` and
  `export ANTHROPIC_API_KEY=…`

### The four commands you'll use most

```bash
# 1. Run the whole gate (semantic + DTD contract tests). Must be green.
pytest -v

# 2. Produce canonical XML for the demo Avaya input.
python src/transform_queue.py fixtures/avaya_queue_sample.csv > out.xml

# 3. Sensor sweep on any output or source file (checks for vocabulary drift).
python src/sensor.py out.xml

# 4. See the AI loop end-to-end for a vendor already in the repo.
python src/automap.py fixtures/vendor_catalogs/avaya_hsplit_fields.yaml --vendor Avaya
python src/verify_mapping.py ontology/proposed/avaya.queue.PROPOSED.yaml \
    fixtures/avaya_queue_sample.csv \
    fixtures/golden/Q_060225.0900.expected.xml
```

**Definition of done** (from `CLAUDE.md`): `pytest -v` is green *and*
`python src/sensor.py <your_output.xml>` reports no drift. If a contract test
fails, fix the mapping — do **not** weaken the test.

### Handy extras

```bash
# The one-shot for adding a new vendor (details below):
./add_vendor.sh <Vendor> <input> [--engine llm]

# Discover mode: turn vendor docs into a field catalog YAML.
python src/discover.py <Vendor> --from-csv <export.csv>
python src/discover.py <Vendor> --doc <file_or_url> [--engine llm]
python src/discover.py <Vendor> --crawl <seed_url>  [--engine llm]  # NEW
```

---

## End-to-end flow (data + control)

Reading top-to-bottom: what happens the first time a new vendor lands.

1. **Discover.** `discover.py` turns any of these into a field catalog:
   - a data export's header row (`--from-csv`),
   - one vendor doc, file or URL (`--doc`),
   - a whole vendor doc site starting from one URL (`--crawl`, new).
   Output: `fixtures/vendor_catalogs/<vendor>.yaml` (field name + one-line
   description; sources recorded in `meta.source`).

2. **Propose.** `automap.py` reads the catalog *and* the canonical ontology
   (`ontology/canonical_wfm.yaml`) and writes an executable proposal —
   one formula per canonical field — with confidence + rationale.
   Output: `ontology/proposed/<vendor>.<report>.PROPOSED.yaml`.

3. **Verify.** `verify_mapping.py` runs the proposal through `engine.py` against
   real data, then diffs the result against the golden XML in
   `fixtures/golden/`. It prints which fields matched and which didn't.

4. **Approve.** A human fixes only the flagged formulas and moves the file to
   `ontology/mappings/<vendor>.<report>.map.yaml` with `status: approved`.
   That approved map is what production runs on.

5. **Run.** `engine.py` executes the approved map against production data to
   produce the NICE WFM Import History XML. `sensor.py` sweeps the output for
   vocabulary drift (any vendor term leaking in, any wrong-unit shape).

6. **Gate.** `pytest -v` and the sensor together are the deterministic gate. A
   change to a mapping is only "done" when the gate is green.

---

## Repository layout

```
ontology/
  canonical_wfm.yaml          # WHAT each WFM concept means — source of truth
  avaya_cms_dialect.yaml      # Avaya CMS  -> canonical, with traps
  genesys_api_dialect.yaml    # Genesys Cloud -> canonical, with traps
  mappings/                   # APPROVED executable maps (status: approved)
  proposed/                   # AI-proposed maps land here before approval
guides/inferential/           # What the AI reads BEFORE coding
  QUEUE_glossary.md, QUEUE_cross_vendor.md, …
schema/HistPlugin.dtd         # DTD used by contract tests
fixtures/
  avaya_queue_sample.csv, genesys_queue_sample.json, …   # sample data
  vendor_catalogs/            # discovered field catalogs (input to automap)
  vendor_docs/                # cached crawled pages (gitignored)
  golden/                     # oracle XMLs the harness grades against
src/
  discover.py                 # DISCOVER: docs/exports -> field catalog
  automap.py                  # PROPOSE:  catalog + ontology -> proposed map
  verify_mapping.py           # VERIFY:   grade proposal vs golden
  engine.py                   # RUN:      executable .map.yaml -> NICE XML
  sensor.py                   # DRIFT:    vocabulary/unit sweep on output
  transform_queue*.py         # reference transformers for the demo
tests/
  test_contract_queue*.py     # semantic + DTD contract tests (the gate)
  test_engine_and_automap.py  # engine + AI-loop tests
  test_discover_crawl.py      # discover.py --crawl unit + E2E tests
docs/superpowers/             # design specs + implementation plans
add_vendor.sh                 # one-shot: DISCOVER -> PROPOSE (all 3 reports)
CLAUDE.md                     # instructions the coding agent reads first
AUTOMAP.md                    # the AI loop, in more detail
README.md                     # public-facing overview
```

---

## Adding a new ACD vendor — step by step

Suppose you're adding **Acme**. The three reports Lexicon supports are
**queue**, **agentqueue**, **agentsystem** — you'll produce a mapping for each.

### Step 0 — Get one of these inputs about Acme

Any of the three is enough to start; the more you have, the better the
discovered catalog.

| You have… | Use… |
| --- | --- |
| a real Acme data export (CSV/TSV) | `--from-csv <file>` (fastest, uses header row) |
| one PDF or one URL of vendor docs | `--doc <file or URL>` |
| a whole vendor documentation site | `--crawl <seed URL>` (new; recommended) |
| already have a hand-made catalog | pass the `.yaml` directly to `add_vendor.sh` |

### Step 1 — Discover: build the field catalog

Fastest path if you have a data export:

```bash
python src/discover.py Acme --from-csv acme_export.csv
```

If you only have documentation:

```bash
# One doc / one URL:
python src/discover.py Acme --doc https://docs.acme.com/wfm/fields --engine llm

# Whole doc site (crawls same host, ≤ 30 pages, ≤ depth 2 by default):
python src/discover.py Acme --crawl https://docs.acme.com/wfm/ --engine llm
```

Output: `fixtures/vendor_catalogs/acme.yaml`. Open it and eyeball the field
descriptions — that's what the AI will reason over next. If a description is
empty, either fill it in or re-run with `--doc`/`--crawl` to enrich.

### Step 2 — Author the dialect file (once per vendor)

The wrapper script (Step 3) scaffolds `ontology/acme_dialect.yaml` for you
straight after discovery — you don't start from a blank file. You can also run
the scaffold on its own:

```bash
python src/scaffold_dialect.py Acme --catalog fixtures/vendor_catalogs/acme.yaml
```

What the scaffold gives you:

- every canonical field for the chosen media scope (default
  `immediate_response`, which skips `SvcLvlPct`/`BackLog*`/`RightParty*`/
  `WrongParty*`), each stubbed at `confirmed: false`;
- `# TRAP:` markers on `HandleTime`, `WorkTime`, `QueueDelayTime`,
  `NotReadyTime` — the slots where past vendors have burned us;
- `drift_watchlist.boundary_terms` pre-populated from every field name in the
  catalog (this is the one thing genuinely derivable — every vendor column IS
  a boundary term by construction).

**What the scaffold cannot do for you:** the mapping itself. Open the stub
and, for each canonical field, fill in the `<vendor>:` term list, the `rule:`
(how to compute from those terms), and — most importantly — the `trap:`
strings that catch semantic drift. Examples of traps that have bitten past
vendors:

- Avaya `acdtime` **excludes** hold time, so `HandleTime = acdtime + holdtime`.
- Genesys `tHandle` **includes** ACW, and is in **milliseconds** — using it
  straight across is wrong twice over.

Flip `confirmed: true` per field only after you've verified against the
vendor's own docs (not just the catalog description, which may itself be
LLM-summarised). Rerunning `add_vendor.sh` will not clobber a hand-edited
dialect — the scaffold step is skipped once the file exists.

If you skip the dialect step entirely the AI still runs, but the trap
detection in the sensor won't know what to watch for.

### Step 3 — Propose: run the auto-mapper

The shortcut is the wrapper script. It runs `discover` (if needed), then
`scaffold_dialect` (only if no dialect exists yet), then `automap` for all
three reports in one shot:

```bash
./add_vendor.sh Acme acme_export.csv        # if you have a CSV export
./add_vendor.sh Acme fixtures/vendor_catalogs/acme.yaml     # if you already have a catalog
./add_vendor.sh Acme https://docs.acme.com/... --engine llm # from a doc URL
```

The script writes three files:

- `ontology/proposed/acme.queue.PROPOSED.yaml`
- `ontology/proposed/acme.agentqueue.PROPOSED.yaml`
- `ontology/proposed/acme.agentsystem.PROPOSED.yaml`

Each proposed field carries a **confidence** and a **rationale**. Reminder from
`AUTOMAP.md`: *don't trust the AI's confidence — verify.*

### Step 4 — Provide a sample data file + a golden XML

Under `fixtures/`:

- `fixtures/acme_queue_sample.<csv|json>` — one interval's worth of real (or
  realistic) data.
- `fixtures/golden/Q_<date>.<time>.acme.expected.xml` — the correct canonical
  XML for that sample, authored or code-generated *once* by an expert.

The golden is the oracle. It's what makes verification deterministic instead of
"looks about right."

### Step 5 — Verify: grade the proposal

For each of the three reports:

```bash
python src/verify_mapping.py \
    ontology/proposed/acme.queue.PROPOSED.yaml \
    fixtures/acme_queue_sample.csv \
    fixtures/golden/Q_<date>.<time>.acme.expected.xml
```

The harness prints which fields match and which don't. Expect the AI to nail
the 1:1 fields and to miss the arithmetic ones (HandleTime, service-level
splits). That's normal — that's what the gate is for.

### Step 6 — Approve: fix the flagged fields and promote

1. Edit the proposed YAML, replacing the wrong formulas with the correct ones
   (guided by the verifier's output and by `ontology/acme_dialect.yaml`).
2. Change `status: proposed` to `status: approved`.
3. Move the file:

   ```bash
   mv ontology/proposed/acme.queue.PROPOSED.yaml \
      ontology/mappings/acme.queue.map.yaml
   ```

4. Repeat for `agentqueue` and `agentsystem`.

### Step 7 — Add a contract test (small, but load-bearing)

Copy `tests/test_contract_queue_genesys.py` to
`tests/test_contract_queue_acme.py` and swap in Acme's sample + golden. The
tests you must keep are:

- **HandleTime = talk + hold** for Acme's dialect.
- **No vendor term leak** (no `acdtime`/`tHandle`/… in the output XML).
- **Units** — durations are seconds, not milliseconds.
- **DTD compliance** — output validates against `schema/HistPlugin.dtd`.
- **Inbound voice** — no `SvcLvlPct`, `BackLog*`, `RightParty/WrongParty`.

### Step 8 — Run the gate

```bash
pytest -v
python src/sensor.py <acme output xml>
```

Both green = the vendor is added. Not green = fix the mapping (or fix the
dialect entry the mapping references), then re-run. Never weaken a contract
test to make it pass.

### Timing expectation

For a mid-complexity vendor with docs and a data sample handy: ~1 hour of
expert time — mostly spent on Step 6 (approving the few fields the AI got
wrong). The catalog, proposal, and boilerplate are all mechanical.

---

## Troubleshooting cheat-sheet

| Symptom | Likely cause | Where to look |
| --- | --- | --- |
| `pytest` fails on `HandleTime` | Forgot to add hold time (Avaya) or divided by 1000 wrong (Genesys) | dialect file + the mapping's `HandleTime` formula |
| `sensor.py` reports a vendor term in the output | The engine is passing a vendor field through untranslated | mapping YAML — the offending canonical field's formula |
| `discover --crawl` fetches 0 pages | Seed URL is JS-rendered, or `robots.txt` disallows it | check `fixtures/vendor_docs/<vendor>/` (nothing there) and the vendor's `/robots.txt` |
| `discover --engine llm` prints a prompt instead of a catalog | `ANTHROPIC_API_KEY` unset or `anthropic` SDK missing | that's the fallback; paste the prompt into Claude to get the catalog |
| DTD validation error | Output XML has an extra/missing tag vs `schema/HistPlugin.dtd` | run the sensor first — it usually points at the culprit |
| A mapping formula looks right but the golden still fails | Unit slip (ms vs s) or arithmetic (excluded/included ACW) | consult the vendor's dialect file's **traps** section |

## Where to go next

- `AUTOMAP.md` — the AI loop, in more depth.
- `guides/inferential/QUEUE_glossary.md` + `QUEUE_cross_vendor.md` — the
  glossary the AI reads before coding. Read them once; they explain most
  of the traps.
- `CLAUDE.md` — the wiring instructions the coding agent obeys.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — design specs and
  implementation plans for recent features (e.g., the `--crawl` mode).
