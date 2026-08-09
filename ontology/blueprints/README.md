# Flow Blueprints — authoring guide

A **Flow Blueprint** is a Markdown document that tells an admin how to configure a specific CRM/CCaaS platform for a specific routing model so it emits ACD-equivalent events. One file per (platform × routing_model) combination.

See `docs/superpowers/specs/2026-08-09-flow-blueprint-design.md` for the full design.

## Files in this directory

- `schema.yaml` — the closed vocabulary all blueprints validate against.
- `events.yaml` — the canonical ACD event taxonomy.
- `<platform>/<routing_model>.md` — one blueprint per combination.

## How to author a new blueprint

1. **Copy `salesforce/queue_based.md`** as a starting template.
2. **Set the frontmatter.**
   - `platform` — must be in `schema.yaml`'s `platforms` list. Add your platform to `schema.yaml` first if it's new (one-line PR).
   - `routing_model` — one of `queue_based | skill_based | presence_aware | overflow_escalation`.
   - `channels` — subset of `voice | chat | messaging | email | case`.
   - `produces_events` — the list of canonical events this configuration produces. Every one MUST appear in `events.yaml`; every one MUST have a matching `### <event>` subsection in section 5.
3. **Fill in the 7 sections** using the CRM-neutral headers exactly:
   - `# Overview` — 1–3 paragraphs. When to use / when not to.
   - `# Prerequisites` — bulleted list.
   - `# Configuration steps` — numbered click-path.
   - `# Object footprint` — Markdown table with the fixed 4 columns (Concept | Platform object.field | Populated when | Notes). Concept values must come from `schema.yaml`'s `concept_vocabulary`.
   - `# ACD event mapping` — one `### <event>` subsection per produces_events entry, with the fixed micro-fields (Recorded in / Trigger / Prerequisite events / Caveats).
   - `# Validation` — how the admin proves the setup works.
   - `# Known traps` (optional but recommended) — platform-specific gotchas.
4. **Validate:** `python -m lexicon.blueprints validate ontology/blueprints/<your_platform>/<your_routing_model>.md`
5. **Get a platform-savvy reviewer to sign off.** The framework can't verify that your Configuration steps actually work end-to-end.

## Adding a new platform

Edit `schema.yaml`, append the platform slug to `platforms`. That's the whole framework change. Then author `<new_platform>/<routing_model>.md`.

## Adding a new canonical concept

Edit `schema.yaml`, append to `concept_vocabulary`. All existing blueprints continue to validate — the vocabulary is additive.

## Adding a new event to the taxonomy

Edit `events.yaml`. New events default to `optional: true` so existing blueprints continue to validate. If you need it to be `optional: false`, you must also add it to every existing blueprint's produces_events + add matching `### <event>` subsections.

## Freshness

- `last_verified` older than 6 months → validator warns.
- `last_verified` older than 12 months → validator errors.

Bump `last_verified` when you re-verify against a new platform release.
