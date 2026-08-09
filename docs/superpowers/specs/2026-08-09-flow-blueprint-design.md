# Design — Flow Blueprint Capability (Lexicon sub-project B2)

- **Status:** Draft, pending review
- **Date:** 2026-08-09
- **Author:** Swapnil Zade (via brainstorming with Claude)
- **Scope:** Sub-project B2 (Flow Blueprint capability) of Lexicon. Sub-projects B1 (fetcher upgrade), B3 (object footprint prediction), B4 (flow-configured mapping) are out of scope for this spec and will be addressed separately.

---

## 1. Context

Sub-project A (discovery deepening) delivered a vendor-agnostic pipeline for **fixed-schema** ACDs like Avaya CMS and Genesys Cloud — systems whose data model is shipped with the product, so a URL to the docs is enough to derive a mapping.

**Flow-configured platforms** (Salesforce Service Cloud with Omni-Channel; Dynamics 365 Customer Engagement; ServiceNow CX; HubSpot Service Hub) do not have a fixed schema for ACD data. Their data footprint is *emergent from configuration*. Whether Salesforce records agent handle time in `AgentWork.EndDateTime - AcceptDateTime` versus a channel-specific event depends on how the customer's admin has configured Omni-Channel routing, presence, and channels. There is no single URL that documents "the schema" — there is a family of possible schemas, each corresponding to a routing model the admin has set up.

The user's original framing (2026-08-09 scoping conversation):

> "now, lexicon should be able to explain that part and should provide who the respective flow can be created in that CRM which will perform those call, consultation, transfer and all other cases with the ACD/CRM system. and based on that provide the data to be mapped."

So the primary bottleneck for flow-configured platforms is not "extract fields from docs" — it is "know which flows the admin must build in the platform, and consequently which objects will hold the data." That knowledge is prerequisite to any downstream discovery or mapping work.

## 2. Goals

- Define a **CRM-agnostic Flow Blueprint framework** — a schema, a canonical event taxonomy, and validation tooling — that any flow-configured platform can plug into as a first-class citizen.
- Author **one reference blueprint** (Salesforce + queue-based routing) as validation that the framework holds up against a real platform.
- Make blueprint validation a first-class CI check: `python -m lexicon.blueprints validate` must run in every test suite.
- Establish the vocabulary and structure that sub-projects B3 (object footprint prediction) and B4 (flow-configured mapping) will consume later, without hard-wiring either.

## 3. Non-goals

- Not building an auth-aware or anti-bot-defeating fetcher. That is sub-project B1.
- Not building an object-footprint-prediction tool that feeds sub-project A's discovery pipeline. That is sub-project B3.
- Not extending sub-project A's mapper to handle Salesforce-style timing composition. That is sub-project B4.
- Not authoring blueprints for platforms beyond Salesforce in v1.
- Not authoring blueprints for skill-based, presence-aware, or overflow-escalation routing in v1 — the framework must support them structurally, but only queue-based is authored as reference.
- Not shipping an LLM-based blueprint drafting tool. That's a follow-up once the framework is stable.
- Not shipping a PDF/HTML renderer. Markdown is the output format; browsers, GitHub, and IDEs all render it natively.
- Not shipping a UI for browsing or editing blueprints.

## 4. High-level architecture

Blueprint = one Markdown file per (platform, routing_model). Framework = schema + event taxonomy + validation tooling.

```
ontology/blueprints/
  schema.yaml                       # closed vocabulary — platforms, routing models, channels, concepts
  events.yaml                       # canonical ACD event taxonomy (vendor-neutral)
  README.md                         # how to author a blueprint
  salesforce/
    queue_based.md                  # v1 reference blueprint
    # skill_based.md, presence_aware.md, overflow_escalation.md — later
  dynamics365/                      # added later
  servicenow_cx/                    # added later

src/lexicon/blueprints/
  __init__.py
  models.py                         # dataclasses
  schema.py                         # loads ontology/blueprints/schema.yaml
  events.py                         # loads events.yaml, validates DAG
  parser.py                         # parses one blueprint.md
  validator.py                      # applies all validation rules
  index.py                          # discovers blueprints on disk
  cli.py                            # list, show, validate commands
  __main__.py                       # `python -m lexicon.blueprints` entrypoint
```

### Design principles

- **Each module has one clear responsibility.** `parser.py` parses; `validator.py` validates; `schema.py` and `events.py` are pure loaders. No cross-responsibility leakage.
- **CRM-neutrality lives in the schema.** The framework's vocabulary (Concept column values, section headers, event names) is CRM-agnostic. Platform-specific terms — `Queue`, `AgentWork`, `PendingServiceRouting` — appear only inside individual blueprints, never in the framework code or schema.
- **Blueprint validity is enforceable in code.** Every blueprint change and every framework change is checked by the validator in CI. No prose-only correctness contracts.
- **No pipeline coupling in v1.** Blueprints are consumed by human admins; sub-project A's discovery pipeline does not consume them. Machine-readable metadata (frontmatter, event taxonomy hints) exists as deliberate hooks for later B3/B4, but nothing in v1 depends on those hooks being used.

## 5. Blueprint schema

### 5.1 File location and naming

`ontology/blueprints/<platform>/<routing_model>.md`. File path must match frontmatter `platform` and `routing_model` values — the validator enforces this.

### 5.2 YAML frontmatter (required unless noted)

```yaml
---
platform: salesforce                                # canonical CRM slug — closed enum from schema.yaml
platform_display_name: "Salesforce Service Cloud"   # human-friendly, appears in rendered doc
routing_model: queue_based                          # one of queue_based | skill_based | presence_aware | overflow_escalation
channels: [voice, chat, messaging, email, case]     # subset of the closed channels enum
version: "1.0"                                      # blueprint's own semver — bump when the doc changes materially
last_verified: 2026-08-09                           # date the author last confirmed against the platform
platform_version_verified_against: "Spring '26"     # so an admin knows if their platform version drifts
authored_by: "Swapnil Zade"                         # informational
produces_events:                                    # canonical ACD events this configuration emits (see events.yaml)
  - interaction.received
  - interaction.routed
  - interaction.accepted
  # ... (see full list in reference blueprint)
tags: [omni-channel, service-cloud-voice]           # optional free-form
---
```

### 5.3 Markdown body — 7 sections, in this order

Every blueprint follows the same structure. The section **names** are CRM-neutral (fixed by the framework); the section **content** is platform-specific.

| # | Section header (fixed) | What goes here |
|---|---|---|
| 1 | `# Overview` | 1–3 paragraphs: what the blueprint accomplishes, when to use it, when NOT to use it. |
| 2 | `# Prerequisites` | Platform features, licenses, permissions the admin must have before starting. Bulleted checklist. |
| 3 | `# Configuration steps` | Numbered click-path or CLI/API instructions to configure the CRM. Screenshots as image links optional. |
| 4 | `# Object footprint` | A table mapping neutral concept → platform object.field. Column set prescribed by schema. |
| 5 | `# ACD event mapping` | For every event in frontmatter's `produces_events`, one `### <event.name>` subsection with a fixed micro-shape. Load-bearing for future B3. |
| 6 | `# Validation` | Steps the admin runs to prove the setup works. |
| 7 | `# Known traps` *(optional but recommended)* | Platform-specific gotchas. |

### 5.4 Object footprint table

Fixed column set, prescribed by `schema.yaml`:

```markdown
| Concept | Platform object.field | Populated when | Notes |
|---|---|---|---|
| routing_entity           | Queue.Name                 | admin creates a Queue | ... |
| routing_entity_member    | GroupMember.UserOrGroupId  | admin adds member     | ... |
| interaction_record       | AgentWork                  | interaction is routed | ... |
# ...
```

The `Concept` column uses a closed vocabulary defined in `schema.yaml`. Any concept not in the vocabulary is either a schema extension (PR to `schema.yaml`) or a blueprint bug.

### 5.5 ACD event mapping subsections

For each event in `produces_events`, exactly one subsection with a fixed micro-shape:

```markdown
### interaction.talk.start
- **Recorded in:** `AgentWork.AcceptDateTime`
- **Trigger:** Agent clicks "Accept" on the Omni-Channel widget.
- **Prerequisite events:** interaction.routed
- **Caveats:** For voice, AcceptDateTime is when the agent accepts in Omni-Channel, not when the voice line actually connects. See Known traps.
```

Required micro-fields: `Recorded in`, `Trigger`, `Prerequisite events`. `Caveats` is optional (warning if absent). This uniform shape is what future B3 will parse.

### 5.6 Validator enforces

- All required frontmatter keys present, correct types.
- `platform`, `routing_model`, `channels` values are in the closed enums from `schema.yaml`.
- Every `produces_events` item exists in `events.yaml`.
- Every `produces_events` item has a matching `### <event>` subsection in section 5.
- Section 5 has no orphan subsections (subsections for events not declared in `produces_events`).
- Object footprint table's `Concept` column uses only the closed vocabulary.
- Object footprint table's columns match the schema exactly.
- File path matches frontmatter: `blueprints/<platform>/<routing_model>.md`.
- Every event's `Prerequisite events` line references events that exist in `events.yaml` (and are also present in `produces_events` if applicable — otherwise warning).
- `last_verified` freshness — warning at 6 months, error at 12.

## 6. Canonical ACD event taxonomy

`ontology/blueprints/events.yaml` — the vendor-neutral catalog every blueprint references.

### 6.1 Structure

```yaml
meta:
  version: "1.0"
  description: "Vendor-neutral catalog of ACD events a flow-configured platform can emit."

presence_states:
  ready:      { description: "Available to receive routed interactions." }
  not_ready:  { description: "Logged in but not available (aux, away, break)." }
  busy:       { description: "Actively handling one or more interactions." }
  acw:        { description: "In after-call-work / wrap-up after an interaction." }
  offline:    { description: "Logged out or ended session." }

events:
  interaction.received:
    description: "An interaction reaches the routing layer."
    prerequisites: []
    optional: false

  interaction.routed:
    description: "Routing layer assigns the interaction to an agent."
    prerequisites: [interaction.received]
    optional: false

  interaction.accepted:
    prerequisites: [interaction.routed]
    optional: false

  interaction.declined:      { prerequisites: [interaction.routed],  optional: true }
  interaction.expired:       { prerequisites: [interaction.routed],  optional: true }

  interaction.talk.start:
    description: "Talk time begins."
    prerequisites: [interaction.accepted]
    optional: false
    projects_to_canonical_wfm: talk_time
  interaction.talk.end:      { prerequisites: [interaction.talk.start], optional: false }

  interaction.hold.start:
    prerequisites: [interaction.talk.start]
    optional: true
    projects_to_canonical_wfm: hold_time
  interaction.hold.end:      { prerequisites: [interaction.hold.start], optional: true }

  interaction.acw.start:
    prerequisites: [interaction.talk.end]
    optional: false
    projects_to_canonical_wfm: acw_time
  interaction.acw.end:       { prerequisites: [interaction.acw.start], optional: false }

  interaction.transferred:
    prerequisites: [interaction.accepted]
    optional: true
    attributes:
      type: { values: [warm, cold, blind] }

  interaction.consulted:     { prerequisites: [interaction.accepted], optional: true }
  interaction.abandoned:     { prerequisites: [interaction.received], optional: false }
  interaction.completed:     { prerequisites: [interaction.acw.end],  optional: false }

  agent.login:               { prerequisites: [], optional: false }
  agent.logout:              { prerequisites: [agent.login], optional: false }
  agent.presence.change:
    prerequisites: [agent.login]
    optional: false
    attributes:
      from_state: { references: presence_states }
      to_state:   { references: presence_states }
```

### 6.2 Design choices

- **Dotted event names** (`interaction.talk.start`) — namespaced by lifecycle grouping. Extensible without breaking anything.
- **`prerequisites` form a DAG.** The event-taxonomy validator checks for cycles and orphans.
- **`optional: bool`** — required-for-completeness events must appear in every blueprint's `produces_events`; optional events (like `hold.*`) are per-blueprint choices.
- **`projects_to_canonical_wfm`** — optional hint pointing at sub-project A's canonical vocabulary. Bridges the two sub-projects. Not load-bearing in v1; enables B4 later without touching this file.
- **`attributes`** — event-specific extra dimensions. Keeps the taxonomy expressive without a combinatorial explosion of event names.

### 6.3 Growth policy

New events land as append-only PRs to `events.yaml`. Since new events default to `optional: true`, existing blueprints remain valid. Removing or renaming an event is a breaking change and requires bumping `events.yaml:meta.version` + updating all blueprints.

## 7. Salesforce reference blueprint

`ontology/blueprints/salesforce/queue_based.md`. One authored Markdown file, following the schema from section 5 with events from section 6.

### 7.1 Frontmatter

```yaml
---
platform: salesforce
platform_display_name: "Salesforce Service Cloud"
routing_model: queue_based
channels: [voice, chat, messaging, email, case]
version: "1.0"
last_verified: 2026-08-09
platform_version_verified_against: "Spring '26"
authored_by: "Swapnil Zade"
produces_events:
  - interaction.received
  - interaction.routed
  - interaction.accepted
  - interaction.declined
  - interaction.expired
  - interaction.talk.start
  - interaction.talk.end
  - interaction.acw.start
  - interaction.acw.end
  - interaction.transferred
  - interaction.abandoned
  - interaction.completed
  - agent.login
  - agent.logout
  - agent.presence.change
tags: [omni-channel, service-cloud]
---
```

Note: `interaction.hold.start`/`.end` deliberately omitted. Salesforce Omni-Channel does not model hold as a first-class event — hold happens inside the underlying channel (voice or chat) and doesn't produce independent `AgentWork` records. Blueprint honestly declares only what this configuration produces; a separate `salesforce/voice_hold_events.md` blueprint can layer on top.

### 7.2 Section contents (sketch)

**Overview** — Salesforce Omni-Channel with queue-based routing: interactions land in one of N Queues; agents matching the Presence Configuration are eligible. Use when a shared pull-style model fits. Use skill-based routing when attribute-based matching is needed.

**Prerequisites** — Service Cloud license; Omni-Channel enabled; admin permissions (Customize Application, Manage Users); voice/messaging add-ons for those channels.

**Configuration steps** (numbered, ~500 words) — Enable Omni-Channel → create Service Channels → create Presence Configuration and Statuses → create Queues + queue members → create OmniChannelRoutingConfig → bind Routing Configuration to Queue → assign Presence Configuration to agent Users.

**Object footprint table:**

```markdown
| Concept                | Platform object.field                | Populated when              | Notes |
|---|---|---|---|
| routing_entity         | Group (Type='Queue').Name            | Admin creates a Queue       | Queues are Groups with Type='Queue' |
| routing_entity_member  | GroupMember.UserOrGroupId            | Admin adds member           | Direct User or nested Public Group |
| interaction_record     | AgentWork                            | Interaction is routed       | One AgentWork per assignment attempt |
| interaction_open       | AgentWork.AcceptDateTime             | Agent accepts               | Null until acceptance |
| interaction_close      | AgentWork.EndDateTime                | Agent closes work           | ACW may follow via CloseDateTime |
| interaction_declined   | AgentWork.DeclineDateTime            | Agent declines              | AgentWork stays; new attempt spawned |
| pending_routing        | PendingServiceRouting                | Interaction awaits routing  | Deleted once routed |
| agent_presence         | UserServicePresence                  | Agent presence changes      | One row per state transition |
| presence_state_type    | ServicePresenceStatus                | Admin defines a status      | StatusOption enum: Online/Away/Offline |
| assignment_rule        | OmniChannelRoutingConfig             | Admin creates routing config| ModelType='LeastActive' or 'MostAvailable' |
```

**ACD event mapping** — 15 subsections, one per `produces_events` entry. Example:

```markdown
### interaction.talk.start
- **Recorded in:** For voice: `VoiceCall.CallStartDateTime`. For chat/messaging: `AgentWork.AcceptDateTime` (used as proxy).
- **Trigger:** Voice line connects OR chat session begins.
- **Prerequisite events:** interaction.accepted
- **Caveats:** Voice channel introduces its own timing which can lag AgentWork acceptance by 1–3 seconds. See Known traps.
```

**Validation** — Log in as agent with Presence Configuration assigned; set presence to Available; have someone create a test Case/Chat and assign to the Queue; confirm AgentWork record created; accept; close; verify AcceptDateTime and EndDateTime populated via SOQL.

**Known traps** — AgentWork.AcceptDateTime ≠ voice line-connect time; PendingServiceRouting rows are transient (deleted after routing); Omni-Channel doesn't record hold as a first-class concept; Queue members can be nested Public Groups requiring recursive walking; Presence auto-away timers cause spurious declines if not tuned.

## 8. Framework tooling and code

### 8.1 Module responsibilities

| Module | Responsibility | Depends on |
|---|---|---|
| `models.py` | Dataclasses: `BlueprintFrontmatter`, `ParsedBlueprint`, `SchemaDef`, `EventTaxonomy`, `EventDef`, `PresenceStateDef`, `ValidationError` | None |
| `schema.py` | Load `ontology/blueprints/schema.yaml` into `SchemaDef` | `models` |
| `events.py` | Load `ontology/blueprints/events.yaml` into `EventTaxonomy`; validate DAG (no cycles, no orphan prerequisites, no invalid attribute references) | `models` |
| `parser.py` | Parse one blueprint.md file into `ParsedBlueprint` (frontmatter dict, ordered section list, event subsection map) | `models` |
| `validator.py` | Apply all validation rules from §5.6 to a `ParsedBlueprint` against `SchemaDef` and `EventTaxonomy`; return `list[ValidationError]` | `models`, `schema`, `events`, `parser` |
| `index.py` | Discover blueprint files on disk (recursively under `ontology/blueprints/`, must have frontmatter starting with `platform:`) | None |
| `cli.py` | `list`, `show`, `validate` commands | all above |
| `__main__.py` | Wire `python -m lexicon.blueprints` to `cli.main` | `cli` |

### 8.2 Key interfaces

**`parser.parse(path: Path) -> ParsedBlueprint`**

```python
@dataclass(frozen=True)
class ParsedBlueprint:
    path: Path
    frontmatter: dict[str, Any]
    sections: list[tuple[str, str]]                # [(header, body), ...] in source order
    event_subsections: dict[str, dict[str, str]]   # {event_name: {"recorded_in": "...", "trigger": "...", ...}}
```

**`validator.validate(bp: ParsedBlueprint, schema: SchemaDef, events: EventTaxonomy) -> list[ValidationError]`**

```python
@dataclass(frozen=True)
class ValidationError:
    path: Path
    severity: Literal["error", "warning"]
    section: str | None
    message: str
```

**`index.discover(root: Path) -> list[Path]`** — enumerates blueprint files.

### 8.3 CLI shape

```bash
python -m lexicon.blueprints list
# Output:
#   PLATFORM         ROUTING            VERSION  VERIFIED
#   salesforce       queue_based        1.0      2026-08-09

python -m lexicon.blueprints show salesforce queue_based

python -m lexicon.blueprints validate                       # validates all; used in CI
python -m lexicon.blueprints validate <path/to/one.md>      # validates one; used on-save
```

### 8.4 `ontology/blueprints/schema.yaml` — the closed vocabulary

```yaml
platforms: [salesforce, dynamics365, servicenow_cx, hubspot_service_hub, generic]
routing_models: [queue_based, skill_based, presence_aware, overflow_escalation]
channels: [voice, chat, messaging, email, case]

required_sections:
  - "Overview"
  - "Prerequisites"
  - "Configuration steps"
  - "Object footprint"
  - "ACD event mapping"
  - "Validation"
# "Known traps" is optional (recommended).

concept_vocabulary:
  - routing_entity
  - routing_entity_member
  - interaction_record
  - interaction_open
  - interaction_close
  - interaction_declined
  - interaction_expired
  - pending_routing
  - agent_presence
  - presence_state_type
  - assignment_rule

object_footprint_columns:
  - Concept
  - "Platform object.field"
  - "Populated when"
  - Notes

event_subsection_fields:
  - "Recorded in"
  - "Trigger"
  - "Prerequisite events"
  - "Caveats"     # last one is optional; warning if absent
```

`platforms` and `concept_vocabulary` are the two most likely to grow. Both are lists — additions are one-line PRs. `routing_models` is expected to stay at four.

## 9. Testing strategy

Three tiers.

### 9.1 Tier 1 — Stage unit tests (fast, deterministic)

- `test_parser.py` — valid frontmatter; missing frontmatter; malformed YAML; section extraction in source order; event-subsection extraction with all micro-fields; edge cases (empty sections, `#` inside code fences, nested headings).
- `test_schema.py` — loads a fixture `schema.yaml`; rejects one missing a required key; sanity checks closed vocabulary sets are non-empty.
- `test_events.py` — loads a fixture `events.yaml`; detects an introduced cycle (`A → B → A`); detects an orphan prerequisite (`X depends on nonexistent Y`); validates that `attributes.references` targets exist in `presence_states`.
- `test_validator.py` — table-driven. One row per validation rule from §5.6, each with fixture blueprint text → expected `ValidationError` list. Plus one valid-baseline row.

### 9.2 Tier 2 — Integration test on the real reference blueprint

- `test_reference_blueprint_validates.py` — runs schema.load → events.load → parser.parse → validator.validate on the actual authored `ontology/blueprints/salesforce/queue_based.md`. Asserts zero errors, warnings allowed for informational reasons.
- Load-bearing regression test. Any framework change or blueprint change must keep this green. If it doesn't, either the change is wrong or the schema needs deliberate updating.

### 9.3 Tier 3 — CLI smoke tests

- `test_cli.py` — subprocess-invokes each of the three commands against a fixture blueprint tree. Asserts exit codes + stdout patterns. Catches wiring errors unit tests wouldn't.

### 9.4 Existing tests unchanged

Sub-project A's 172-test suite remains untouched. Adding B2 files does not touch A's code paths. `pytest -v` continues to run everything.

## 10. Determinism

All I/O is file reads. No network. No LLM. Every test runs deterministically. `python -m lexicon.blueprints validate` in CI completes in under 1 second on the committed tree.

## 11. Success criteria for v1

- **Framework is complete and consistent.** `schema.yaml` + `events.yaml` load without errors; the DAG in events.yaml has no cycles; the two files are internally coherent.
- **Validator catches all documented failure modes.** Each has a passing unit test.
- **Salesforce queue_based reference blueprint validates cleanly.** Zero errors; warnings only for informational reasons.
- **Reference blueprint is a real document.** A Salesforce-savvy reviewer (human) reads it end-to-end and signs off that an admin following it will produce the declared events. This is a judgement criterion; automated tests cannot verify it.
- **`python -m lexicon.blueprints validate` runs in under 1 second** and returns exit 0 on the committed tree.
- **CRM-neutrality is enforced in code, not just docs.** Grep-test: `grep -r salesforce src/lexicon/blueprints/` returns zero hits. The framework code does not mention any specific platform.
- **No existing test regresses.** `pytest -v` remains green.

## 12. Risks and open questions

| Risk | Mitigation |
|---|---|
| The Salesforce reference blueprint depends on Omni-Channel expertise the author doesn't fully have | Ship what's authorable; mark uncertain sections with `⚠` and `TODO(SF-expert)`; extend validator to flag such markers to prevent them persisting |
| Neutral vocabulary in `schema.yaml` might be too Salesforce-shaped by accident | Before writing the blueprint, rehearse the vocabulary against Dynamics 365 CIF and ServiceNow CX docs (no blueprints authored, just vocabulary check); adjust once |
| `events.yaml` might miss an event a real integration needs | `optional: true` events allow additions post-v1 without breaking existing blueprints; new events land as small PRs |
| `last_verified` dates go stale silently | Validator emits warning at 6 months, error at 12 months (configurable). Encourages periodic re-review |
| Framework generates admin frustration if it doesn't match how they think | Post-authoring smoke-test: hand the reference blueprint to a Salesforce admin who hasn't seen it, watch them configure Omni-Channel following it, capture friction. Feed back into v1.1. |

Open questions for implementation-time follow-up:

- Whether `blueprint.md` should have a fixed filename (e.g., `queue_based.md`) or be discoverable by frontmatter alone. Current design uses filename-based discovery (`<platform>/<routing_model>.md`). Fine for v1.
- Whether `python -m lexicon.blueprints show` should invoke `$PAGER` when stdout is a TTY, or always dump raw. Design chooses raw dump; can add PAGER later if pain surfaces.
- Whether the `Caveats` micro-field in event subsections should be required (currently optional with warning). Trade-off between honesty pressure on authors and false positives.

## 13. Relationship to sub-project A (in v1)

Sub-project A's discovery pipeline (already implemented) is untouched. Blueprints do NOT feed the pipeline in v1. Two future integration points, both out of scope:

- **B3 (future)** — a tool reads a blueprint's Object Footprint table, produces a list of platform objects/fields, and feeds them as `SourceDoc`s into sub-project A's extract stage.
- **B4 (future)** — a mapper extension consumes the ACD event mapping section, uses the `projects_to_canonical_wfm` hints in `events.yaml`, and composes canonical WFM formulas (e.g. `talk_time = interaction.talk.end - interaction.talk.start`).

The `projects_to_canonical_wfm` field in `events.yaml` is a **deliberate hook** for B4 — present but unused by v1's tooling. This lets B4 land later without touching `events.yaml`.

## 14. Out of scope (explicit — for future spec-writers)

- Auth-aware / anti-bot fetcher — sub-project B1.
- LLM-based blueprint drafting — post-v1 follow-up (Approach 3).
- Object footprint prediction that feeds discovery — sub-project B3.
- Flow-configured mapping to canonical WFM — sub-project B4.
- PDF/HTML rendering — Markdown is the output.
- Admin UI for browsing/editing blueprints — could be built later; not v1.
- Blueprint-driven test harness that spins up a Salesforce sandbox — large infra investment; possibly Sub-project B5.

---

## Appendix A — File-and-directory delta

New:

```
ontology/blueprints/
  README.md                                    # authoring guide
  schema.yaml                                  # closed vocabulary
  events.yaml                                  # canonical ACD event taxonomy
  salesforce/
    queue_based.md                             # v1 reference blueprint

src/lexicon/blueprints/
  __init__.py
  models.py
  schema.py
  events.py
  parser.py
  validator.py
  index.py
  cli.py
  __main__.py

tests/lexicon/blueprints/
  test_parser.py
  test_schema.py
  test_events.py
  test_validator.py
  test_reference_blueprint_validates.py
  test_cli.py
```

No existing file modified.

## Appendix B — CLI shape (informational)

```bash
# Enumerate all blueprints
python -m lexicon.blueprints list

# Print one blueprint to stdout (or $PAGER later)
python -m lexicon.blueprints show salesforce queue_based

# Validate all blueprints (used in CI)
python -m lexicon.blueprints validate

# Validate one file (used in editor on-save hook)
python -m lexicon.blueprints validate ontology/blueprints/salesforce/queue_based.md
```
