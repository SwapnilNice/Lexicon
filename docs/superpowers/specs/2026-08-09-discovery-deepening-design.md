# Design — Discovery Deepening (Lexicon sub-project A)

- **Status:** Draft, pending review
- **Date:** 2026-08-09
- **Author:** Swapnil Zade (via brainstorming with Claude)
- **Scope:** Sub-project A of Lexicon productionization. Sibling sub-projects (B — flow-aware discovery for CRM/CCaaS; C — canonical layer generalization; D — packaging/CI/observability) are out of scope for this spec and will be addressed separately.

---

## 1. Context

Lexicon today turns ACD vendor data (Avaya CMS, Genesys Cloud) into NICE WFM Import History XML via an AI-in-the-loop pipeline: `discover → propose → verify → approve`. The Sparkathon POC demonstrated that the mapping step is tractable — an AI proposes formulas, a deterministic harness catches its mistakes, a human ratifies the flagged fields.

In practice, however, **mapping is not the bottleneck. Discovery is.** Expert time onboarding a new ACD is spent overwhelmingly on:

- finding the vendor's authoritative documentation (which URL? which manual? which API schema?),
- deciding which extraction mode to run (`discover.py --crawl`, `--doc`, `--from-csv`),
- verifying that the resulting field catalog is complete enough to hand to the mapper.

Today's `discover.py` requires the human to do all of that work. The user's stated wish: give Lexicon a vendor **name** and get back a catalog rich enough that mapping is nearly automatic.

Two additional constraints frame this work:

1. **Pre-customer**: integrations are built before any customer exists on the platform. Discovery must work from **vendor-published public artifacts only** — no dependence on customer CSV/JSON exports.
2. **Vendor-agnostic pipeline**: the discovery *method* is a single universal pipeline; per-vendor code is not acceptable. Adding a vendor should be a small YAML registry entry, not a source-code change.

## 2. Goals

- One-command entrypoint: `lexicon discover <vendor>` where the only input is the vendor name.
- Produce a **rich** vendor catalog: for every vendor field, capture name, description, unit, semantic tag, source provenance, and a candidate canonical mapping with honest confidence.
- Absorb today's `automap.py` propose step into discovery — the human sees a proposed mapping ready to hand to `verify_mapping.py`.
- Reproduce the current Avaya mapping (10/10 correct) end-to-end from public docs alone. Reproduce Genesys mapping including the two hardest cases (ACW-excluded HandleTime, ms→s conversion).
- Keep the existing gate green: `pytest -v` and `sensor.py` still enforce correctness. Discovery must not weaken either.

## 3. Non-goals

- Not building flow-aware discovery for CRM/CCaaS platforms (Salesforce, D365, ServiceNow CX). That is sub-project B.
- Not refactoring the canonical ontology into a product-neutral layer with per-product projections. That is sub-project C, deferred until a concrete second NICE product has real requirements.
- Not shipping packaging, CI, containerization, or structured logging. That is sub-project D.
- Not supporting JS-rendered documentation via headless browsers, PDF sources, or auth-gated documentation in v1.
- Not building an embedding-based cross-vendor similarity index or confidence-calibration dashboard. Both are attractive but premature without prior runs.

## 4. High-level architecture

One user-facing verb; five internal stages; one durable artifact per vendor.

```
$ lexicon discover "Avaya CMS"
        │
        ▼
[1] Vendor resolver     — registry lookup, web-search fallback
        │
        ▼
[2] Source fetcher      — HTML crawler + API schema parser
        │
        ▼
[3] Field extractor     — structural (tables/schemas/lists) + LLM prose fallback
        │
        ▼
[4] Enricher            — unit inference, semantic tagging, dedupe, trap detection
        │
        ▼
[5] Mapper              — proposed canonical mapping per field, with honest confidence
        │
        ▼
fixtures/vendor_catalogs/<slug>.yaml       # rich catalog
ontology/proposed/<slug>.<report>.PROPOSED.yaml   # proposed mapping (unchanged shape)
out/discovery_reports/<slug>.md            # human-readable coverage report
```

### Design principles

- **Each stage is a deep, isolated module with a narrow interface** (input artifact → output artifact). Every stage is independently testable; intermediates are cached so any single stage can be rerun without redoing prior work.
- **Structural signals beat LLM signals** wherever both are available. LLM is used only when structural extraction is silent or ambiguous. This keeps runs reproducible and cheap.
- **Confidence is emitted but never trusted blindly.** The verify step (unchanged from today) is the trust root. Discovery's job is to produce the best proposal possible; verify's job is to grade it.
- **Nothing depends on customer data.** Public vendor artifacts only in v1.

### What this replaces vs. preserves

| Today | v1 |
|---|---|
| `discover.py --crawl <url>` / `--doc <file>` / `--from-csv` | `lexicon discover <vendor>` — name in, artifacts out. `--from-csv` remains as a legacy convenience mode, not the primary path. |
| `automap.py <catalog> --vendor X` | Folded into the discovery Mapper stage. |
| `fixtures/vendor_catalogs/<v>.yaml` (name + one-line description) | Same path, richer content (unit, semantic tag, source, snippet, candidate mapping, confidence, traps). |
| `ontology/proposed/<v>.<report>.PROPOSED.yaml` | Same path and shape. `verify_mapping.py` / approve / `engine.py` unchanged. |

## 5. Vendor registry

### Purpose

A curated set of small YAML files — one per known ACD — that resolves a user-supplied name to a set of authoritative sources. The registry is **hints, not truth**: if an entry is stale or a URL 404s, the search fallback runs and the pipeline still succeeds.

### Location & shape

`ontology/registry/<slug>.yaml`, mirroring the existing "one file per thing" convention. Example:

```yaml
slug: avaya_cms
name: "Avaya CMS"
aliases: ["Avaya", "Avaya Call Management System", "CMS Historical"]
category: fixed_schema                    # fixed_schema | flow_configured (matters for sub-project B)
description: "Historical reporting DB for Avaya Aura CC; hsplit/hagent tables."

sources:
  - kind: html_doc
    role: primary
    url: https://documentation.avaya.com/.../DatabaseInfoSplitskillDatabaseItems.html
    crawl:
      max_depth: 2
      max_pages: 30
      include_paths: ["/DatabaseInfoDatabaseTables/"]
  - kind: openapi
    role: primary
    url: null                             # not applicable for CMS

version:
  system_version: "R21"
  last_verified: 2026-08-09
```

Traps and dialect knowledge do **not** live in the registry — they live in dialect files, where they always have. The registry knows only "where to look."

### Name resolution rules

- Case-insensitive substring + alias match against `name` and `aliases`.
- **Unique match** → resolve to slug.
- **Multiple matches** → fail fast, print candidates, require the user to invoke by slug (`lexicon discover avaya_cms`). Deterministic and CI-safe.
- **No match** → search fallback.
- User can always bypass resolution by passing the slug directly.

### Search fallback

1. Templated web-search query: `"<vendor>" (contact center OR ACD) (data model OR schema OR historical) site:docs.* OR site:developer.* OR site:help.*`
2. Rank results by domain authority (vendor's own domain wins), page markers (`docs`, `developer`, `help`, `admin`, `api`), and content signals (presence of field-definition tables or schemas).
3. Present the top 3 candidates interactively, or take top 1 non-interactively.
4. Persist the resolution in `state/discovery_cache/<slug>.resolution.yaml` so re-runs are deterministic and cheap.
5. **Registry promotion**: on a successful search-fallback run, offer to write `ontology/registry/<slug>.yaml` for the user to review and PR. Each unknown-vendor run enriches the registry over time.

### Failure modes

| Situation | Behavior |
|---|---|
| Vendor's doc URL 404s | Log, fall back to search or secondary sources |
| Crawl fetches 0 pages (robots.txt / JS-rendered) | Log, fall back to search or secondary sources |
| Search returns nothing useful | Fail with an actionable message |
| Multiple candidates and non-interactive | Fail with candidate list; require slug |
| Registry entry stale (fields changed) | Discovery still runs; coverage report flags the drift |

### Explicit non-goals for the registry

- No auto-updating of registry entries. `last_verified` is informational; humans refresh.
- No versioning beyond git history.
- No external hosting. Registry lives in-repo.

## 6. Source fetcher

### The `SourceDoc` seam

The fetcher normalizes disparate input into a uniform `SourceDoc` list, so no downstream stage cares whether a document came from HTML or an API schema. Adding a new source kind (PDF later, e.g.) is a new fetcher strategy that emits `SourceDoc`s — no downstream changes.

### Strategies

| Strategy | Fetches | Emits |
|---|---|---|
| `html_doc` | Crawls URLs bounded by `robots.txt`, same-host, `crawl.max_depth` / `max_pages` / `include_paths`. Enhances the existing `--crawl`. | `SourceDoc(kind="html", url, title, content=<clean HTML>, text=<extracted text>)` per page |
| `openapi` | Fetches schema URL, resolves `$ref`s in place. | `SourceDoc(kind="openapi_schema", url, title=<schema name>, content=<normalized dict>)` per named schema/object |
| `graphql` | Runs introspection or parses SDL. | `SourceDoc(kind="graphql_type", ...)` per named type |
| `wsdl` | Parses WSDL tree. | `SourceDoc(kind="wsdl_type", ...)` per named type |

### Cache layout

```
fixtures/
  vendor_docs/<slug>/           # HTML pages (gitignored, existing convention)
    <sha256>.html
    _index.json                 # url → filename + fetched_at
  vendor_schemas/<slug>/        # NEW: normalized API schema snapshots
    openapi.resolved.json       # $refs inlined
    graphql.introspection.json
    _index.json
```

Content-addressed by URL + fetch time. Every downstream artifact records the exact `SourceDoc` ids and fetch timestamps it was built from — reproducibility guaranteed.

### Freshness policy

- Default: use cache if entry is < 30 days old (configurable).
- `--refresh` forces re-fetch of all sources for the vendor.
- CI runs `--offline`: cache miss = loud failure. Guarantees fixtures are current.

### Failure handling

- Per-source failures are **soft**: partial success continues, coverage report notes gaps.
- All sources fail → hard fail with actionable diagnostics (URLs, HTTP codes, `robots.txt` decisions, JS-rendering indicators).

## 7. Field extractor

Consumes `SourceDoc` list, emits `RawField` list. One `RawField` per (source, field-mention). Duplicates resolved later in the enricher.

### Strategy pattern per `SourceDoc.kind`

| Kind | Extractor | Method |
|---|---|---|
| `html` (structured) | HTML DOM walker | `<table>` with field/description columns; `<dl><dt><dd>` definition lists; headings followed by paragraphs. No LLM. |
| `html` (prose leftover) | LLM prose extractor | Runs only on HTML regions the structured extractor did not consume. Prompt asks for `(field name, one-sentence description)`. Cached by content hash. |
| `openapi_schema` | Schema walker | Iterates `properties`; pulls `description`, `type`, `format`, `x-*` extensions. |
| `graphql_type` | Introspection walker | Same, over `fields` and `types`. |
| `wsdl_type` | XSD walker | Same, over `element` / `complexType`. |

### `RawField` shape

```yaml
name: "acdtime"
description: "Talk time of all ACD calls; does NOT include holdtime."
source:
  doc_id: page:37
  url: https://documentation.avaya.com/.../DatabaseInfoSplitskillDatabaseItems.html
  locator: "table.field-listing > tr:nth-child(12)"    # DOM selector, or JSON pointer for schemas
  snippet: "ACDTIME — Talk time of all ACD calls..."
extractor: html_structured                              # or llm_prose | openapi | graphql | wsdl
confidence_extraction: 0.98                             # structural=high, LLM=lower
```

The extractor is deliberately dumb about meaning. It captures *what the document says* about each field. Semantic reasoning is the enricher's job.

## 8. Enricher

Consumes `RawField` list, emits `EnrichedField` list. Four sub-steps in order.

### 8.1 Dedupe and merge

Fields with normalized-equal names (case-insensitive, punctuation-stripped) collapse to one entry. Provenance is preserved as a *list* of sources. Multiple sources agreeing on the definition → `confidence_extraction` boost. Disagreeing definitions → flagged `conflict` for human review.

### 8.2 Unit inference

Layered signals, cheapest first. Each contributes to `unit_confidence`; `unit: unknown` is emitted rather than guessing on silence.

| Signal | Example | Strength |
|---|---|---|
| Name suffix | `*_ms` → ms; `*_seconds` → s; `*Pct` → % | strong |
| OpenAPI `format` / `x-unit` | `type: integer, format: int64, x-unit: milliseconds` | strong |
| Description regex | "in milliseconds", "seconds", "percent", "count of" | medium |
| LLM classifier | runs only when the above are silent or contradictory | weakest |

### 8.3 Semantic tagging

Each enriched field is tagged with zero or more canonical concept families from `canonical_wfm.yaml`, with weights. Signals:

- Name/description similarity to the canonical field's definition (LLM classifier, cached).
- Vendor-agnostic keyword lexicon: `{talk, converse, chat_time}` → `talk_time_like`; `{hold, park}` → `hold_time_like`; `{wrap, acw, after_call}` → `acw_time_like`; `{ready, available, idle}` → `ready_time_like`; and so on.

Multi-tag allowed. Example: `avaya.acdtime` → `[{tag: talk_time_like, weight: 0.95}]`.

### 8.4 Trap detection

Pattern scan for known semantic traps:

- "does NOT include" / "excludes" → `trap: {kind: exclusion, target: <inferred concept>}`
- "includes" / "combined with" → `trap: {kind: inclusion, target: ...}`
- Unit mismatch with peer fields (all other durations are seconds, this one is ms) → `trap: {kind: unit_slip}`

Traps flow into the mapper (Section 9) and become `# TRAP:` comments in the proposed mapping.

### `EnrichedField` shape

```yaml
name: acdtime
description: "Talk time of all ACD calls; does NOT include holdtime."
sources: [ {url: ..., snippet: ...}, {url: ..., snippet: ...} ]    # merged
unit: duration_seconds
unit_confidence: 0.9
unit_signals: [name_suffix:absent, description_regex:"seconds"→s, llm:s]
semantic_tags:
  - {tag: talk_time_like, weight: 0.95, rationale: "explicit talk time, excludes hold"}
traps:
  - {kind: exclusion, target: hold_time, evidence: "does NOT include holdtime"}
```

### Cost and determinism

- **All LLM calls cached** by `(model, prompt, input hash)`. Re-runs on unchanged sources are free.
- **LLM never used where a structural signal exists.** If OpenAPI says `x-unit: ms`, no LLM query is made.
- **Two-model discipline**: small model (Haiku) for cheap classification (unit signal, semantic tag); larger model (Sonnet) only for prose extraction where quality matters.

## 9. Mapper

Takes `EnrichedField`s + `canonical_wfm.yaml` and produces the same-shape artifact today's `automap.py` produces — but with better data going in, so the proposal is right more often.

### Algorithm (per canonical concept)

For each concept `C` in `canonical_wfm.yaml` filtered to the current report (queue / agent_queue / agent_system):

1. **Shortlist** enriched fields whose `semantic_tags[].tag` matches `C`'s expected tag family with `weight ≥ 0.4`.
2. **Unit filter** — drop candidates where `unit != C.unit`, unless a trap flags a needed conversion (e.g., ms → s).
3. **Rank** by `weight × unit_confidence × extraction_confidence`.
4. **Compositional concepts** — if `C` has a derivation pattern (see 9.1), fill each component from the shortlist and compose the formula.
5. **Emit** the top candidate as the proposal, plus up to two alternates, plus rationale.

### 9.1 Additive derivations in the canonical file

The existing `canonical_wfm.yaml` documents compositions in prose (`HandleTime = talk + hold, excludes ACW`). To let the mapper compose formulas automatically, add an optional `derivation:` block per canonical field. **Additive, non-breaking**: existing fields unchanged; only new machine-readable metadata is added where composition is needed.

```yaml
# canonical_wfm.yaml (proposed additive block — nothing existing changes)
queue:
  HandleTime:
    definition: "Total handle time = TALK + HOLD. Does NOT include ACW."    # unchanged
    unit: duration_seconds                                                  # unchanged
    derivation:                                                             # NEW, optional
      components:
        - {tag: talk_time_like, required: true}
        - {tag: hold_time_like, required: true}
      formula: "{talk} + {hold}"
      forbid_tags: [acw_time_like]     # mapper never proposes talk+hold+acw
```

Leaf concepts (`HoldTime`, `WorkTime`, `AgentValue`, etc.) need no `derivation` block — the mapper picks the top-ranked candidate directly.

### 9.2 Trap-aware composition

When the enricher flags `acdtime` with `trap: {kind: exclusion, target: hold_time}`, the mapper uses that trap to find the exclusion partner (a `hold_time_like` field — `holdtime`) and generates `acdtime + holdtime` for `HandleTime`. This is the mechanism that turns today's classic Avaya failure into a first-time success.

### 9.3 Confidence rubric — the honest one

The whole project thesis is "don't trust AI confidence." The rubric caps aggressively:

| Signal quality | Confidence range |
|---|---|
| Schema `$ref` exact match + structural unit + tag agree | 0.9 – 1.0 |
| HTML table match + structural unit + tag agree | 0.75 – 0.9 |
| Composition of two candidates each ≥ 0.75 | `min(components)` |
| LLM-classified only, one signal | 0.4 – 0.6 |
| LLM-classified with source disagreement | ≤ 0.4 |
| Single weak keyword hit | 0.2 – 0.35 |
| Below 0.2 | not emitted |

Hard cap: **LLM-only proposals never exceed 0.85**, no matter the model's self-reported confidence. Structural sources are the only path to 0.9+.

### 9.4 Output artifact

Same file the human already reviews — `ontology/proposed/<slug>.<report>.PROPOSED.yaml` — so `verify_mapping.py` / approve / `engine.py` are unchanged.

```yaml
meta:
  vendor: avaya_cms
  report: queue
  status: proposed
  produced_by: lexicon-discover
  produced_at: 2026-08-09T14:00:00Z
  ontology_version: canonical_wfm.yaml@<git-sha>
fields:
  HandleTime:
    formula: "acdtime + holdtime"
    confidence: 0.88
    rationale: "Compositional: talk_time_like=acdtime (0.95, HTML table + trap:excludes hold); hold_time_like=holdtime (0.93, HTML table). Formula from canonical derivation."
    alternates:
      - {formula: "acdtime", confidence: 0.4, note: "single-field candidate — would be wrong; excludes hold per source snippet"}
```

### 9.5 Ambiguity policy

- Two candidates within 5% confidence → both emitted (primary + alternate); coverage report flags as "human choice."
- No candidate above 0.4 → emit `formula: null, confidence: 0.0, needs_human: true` with reason. Coverage report groups as "missing."
- Partial composition (found `talk_time_like` but not `hold_time_like`) → single-field candidate at reduced confidence with a rationale naming the missing component.

## 10. Coverage report

Written to `out/discovery_reports/<slug>.md` at the end of every run. Human-readable, opinionated about what matters.

```markdown
# Discovery report — Avaya CMS (2026-08-09T14:00Z)

## Sources
- ✓ https://documentation.avaya.com/.../hsplit  (37 pages, 30 days old, cached)
- ✗ https://documentation.avaya.com/.../legacy  (404, skipped)

## Canonical coverage (queue report, immediate_response scope)
| Canonical concept | Status | Proposed | Confidence |
|---|---|---|---|
| QueueValue | ✓ found | split | 0.98 |
| HandleTime | ✓ found (composed) | acdtime + holdtime | 0.88 |
| WorkTime | ✓ found | acwtime | 0.95 |
| AbandonedShort | ⚠ low confidence | slvlabns | 0.55 |
| SvcLvlPct | — ignored per media policy |  |  |
| ContactsActive | ✗ missing | (none plausible) | 0.0 |

Overall: 8/10 required concepts found, 1 low-confidence, 1 missing.

## Traps flagged
- acdtime — "does NOT include hold" (exclusion) → informed composition ✓

## Ambiguities
- (none)

## Cost
- LLM calls: 42 (cached: 38, live: 4) — Haiku 0.02 USD, Sonnet 0.00 USD
- Wall time: 34s

## Next actions for the human
1. Verify AbandonedShort=slvlabns against a real hsplit sample.
2. Decide ContactsActive: does hsplit have a carryover metric, or is it derived?
```

The coverage report lands in the git history alongside the catalog — a year from now, a reviewer can see what evidence produced the mapping.

## 11. Testing strategy

Three tiers, each with a clear job.

### 11.1 Stage unit tests (fast, deterministic, no network, no LLM)

- `test_extractor_html.py` — fixture HTML fragments → expected `RawField` list.
- `test_extractor_openapi.py` — fixture OpenAPI JSON → expected `RawField` list.
- `test_enricher_unit_inference.py` — rule-based unit-signal table.
- `test_enricher_semantic_tag.py` — canned enriched fields → expected tag assignments.
- `test_mapper_composition.py` — canned enriched fields → expected formula and confidence range.

Covers ~90% of pipeline logic without touching network or LLM.

### 11.2 End-to-end regression tests (cache-only)

- `test_discover_avaya_cms.py` — run pipeline against committed Avaya CMS doc snapshot; assert:
  - Registry resolution → `avaya_cms`.
  - Coverage ≥ 8/10 concepts for queue report.
  - `HandleTime.formula == "acdtime + holdtime"` — the punchline test.
  - `WorkTime.formula == "acwtime"`.
  - No LLM-only proposal above 0.85.
- `test_discover_genesys_cloud.py` — Genesys punchlines: ms → s conversion + ACW-excluded HandleTime, both must be right.

### 11.3 Existing contract tests (unchanged)

`test_contract_queue.py`, `test_contract_queue_genesys.py`, DTD validation, sensor drift — all continue to run on the WFM XML produced by `engine.py`. The engine and its input format do not change, so these are stable.

## 12. Determinism guarantees

- All HTTP fetches cached by URL + content hash. Re-runs against committed fixtures never hit the network.
- All LLM calls cached by `(model, prompt, input hash)`. Re-runs never hit the LLM API.
- CI runs in `--offline` mode: any cache miss fails the run. Guarantees the fixtures are current and forces intentional refresh.

## 13. Success criteria for v1

- `lexicon discover avaya_cms` reproduces the current Avaya mapping (10/10 fields correct) from URL + registry only. Today's `automap.py` gets 5/10. This is the delta this project must deliver.
- `lexicon discover genesys_cloud` gets ≥ 8/10 correct including HandleTime trap and ms → s conversion.
- A brand-new vendor with a registry entry and public docs produces a catalog + proposal in ≤ 5 minutes wall clock, with a coverage report actionable in ≤ 15 minutes.
- No existing test regresses. `pytest -v` stays green.

## 14. Risks and open questions

| Risk | Mitigation |
|---|---|
| LLM prose extraction produces plausible-sounding wrong descriptions | Cross-check against structural signals; cap LLM-only confidence at 0.85; verify step remains the trust root |
| Vendor changes docs URL structure → registry entries go stale | `last_verified` timestamp + coverage report flags drift; search fallback keeps runs working |
| Search fallback returns spam/marketing pages, not authoritative docs | Domain-authority ranking + content signals (must contain field-definition tables/schemas); top-3 interactive review |
| Semantic keyword lexicon is English-only | Documented non-goal; revisit when a non-English vendor is on the roadmap |
| Determinism erodes over time as LLM/model changes | Cache is keyed on model + prompt; upgrading models invalidates cache intentionally |

Open questions for implementation-time follow-up:

- Exact confidence thresholds may need tuning against the two anchor vendors (Avaya, Genesys) once the pipeline is running.
- Whether `state/discovery_cache/` is the right home for search-fallback resolutions, or whether that belongs under `fixtures/`.

## 15. Out of scope (explicit, for future spec-writers)

- Flow-aware discovery for CRM/CCaaS (Salesforce, D365, ServiceNow CX) — sub-project B.
- Product-neutral canonical layer + per-product projections — sub-project C.
- Packaging, CI, containerization, structured logging — sub-project D.
- JS-rendered documentation via headless browsers.
- PDF sources.
- Auth-gated documentation.
- Embedding-based cross-vendor similarity.
- Confidence-calibration dashboard.

---

## Appendix A — File-and-directory delta

New:

```
ontology/registry/                           # per-vendor registry entries
  avaya_cms.yaml
  genesys_cloud.yaml
fixtures/vendor_schemas/<slug>/              # cached API schema snapshots (gitignored)
out/discovery_reports/<slug>.md              # per-run coverage report
state/discovery_cache/<slug>.resolution.yaml # search-fallback resolutions
src/lexicon/                                 # new package (structure TBD in plan)
  discover/
    resolver.py                              # stage 1 — vendor resolver
    fetch/                                   # stage 2 — source fetcher strategies
      html.py
      openapi.py
      graphql.py
      wsdl.py
    extract/                                 # stage 3 — field extractors
      html_structured.py
      llm_prose.py
      openapi.py
      graphql.py
      wsdl.py
    enrich/                                  # stage 4 — enrichment
      dedupe.py
      unit_infer.py
      semantic_tag.py
      trap_detect.py
    mapper.py                                # stage 5 — mapping
    report.py                                # coverage report writer
    cli.py                                   # `lexicon discover` entrypoint
```

Modified:

- `ontology/canonical_wfm.yaml` — additive `derivation:` blocks on compositional fields (`HandleTime`, service-level splits). No existing field changed.
- `src/discover.py` — kept for backward compatibility; internally delegates to the new pipeline. `--from-csv` remains as a legacy mode.
- `src/automap.py` — kept for backward compatibility; internally delegates to the new Mapper stage.

Unchanged (deliberately):

- `src/engine.py`, `src/verify_mapping.py`, `src/sensor.py` — no changes.
- `ontology/mappings/*.map.yaml`, `ontology/avaya_cms_dialect.yaml`, etc. — no changes.
- `schema/HistPlugin.dtd`, existing contract tests — no changes.
- `add_vendor.sh` — internally invokes `lexicon discover` where it invoked `discover.py` + `automap.py` before; user-facing behavior unchanged.

## Appendix B — CLI shape (informational)

```bash
# The common case
lexicon discover avaya_cms

# Vendor name (registry resolves)
lexicon discover "Avaya CMS"

# Refresh cached sources
lexicon discover avaya_cms --refresh

# Non-interactive (fail on ambiguity, no search-fallback prompts)
lexicon discover avaya_cms --non-interactive

# Cache-only, no network or LLM (for CI)
lexicon discover avaya_cms --offline

# Just resolve, don't run downstream stages (for debugging)
lexicon discover avaya_cms --stage resolve

# Only re-run enrichment + mapping against cached extraction (for iteration)
lexicon discover avaya_cms --stage enrich mapper
```
