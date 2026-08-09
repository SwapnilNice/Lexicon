# Sparkathon 2026 — Pitch Notes for Lexicon

Working notes distilled from a long conversation about (1) what the current
code implements vs the original pitch doc, and (2) how to sharpen the pitch
given the operational reality: NICE builds ACD→WFM integrations, one per
vendor/customer, and once a mapping is authored it stays stable.

---

## Part 1 — Is this project genuinely useful, or is Claude alone enough?

### The 80% the "just ask Claude" argument is right about

For the **authoring** step (produce a mapping the first time), a competent
engineer sitting with Claude and the vendor's schema PDF can produce a
defensible dialect in 30-60 minutes. No pipeline needed. Concretely, the
following components of the current code are largely redundant if the human
is willing to work interactively with Claude:

| Component | What it does | Could be replaced by |
| --- | --- | --- |
| `discover.py` | Extract vendor fields from PDF | Paste PDF into Claude, ask for the field list |
| `automap.py` | AI-propose vendor→canonical mappings | Ask Claude for the mapping directly |
| `scaffold_dialect.py` | Generate the empty stub | Ask Claude to write the dialect |
| `add_vendor.sh` | Orchestrate the above | Not needed |
| Vendor catalog YAML | Intermediate artifact | Skip; Claude reads vendor doc directly |

If you cut these, you lose ~40% of the current code and lose almost nothing
of substance for authoring. In this very conversation, my dialect authored
by reading `metrics-definitions.md` was clearly better than the one
`automap.py` produced.

### The 20% Claude alone cannot replace (where Lexicon's real value lives)

1. **Deterministic runtime.** You can't run Claude on every 15-minute
   interval of a customer's data — cost and latency prohibit it. You need
   `engine.py` running `.map.yaml` files cheaply and deterministically.
   **The mapping YAML is the durable artifact; the pipeline exists to
   produce it once and then execute it forever.**

2. **Regression protection over time.** Even if the mapping itself doesn't
   change, someone touching `engine.py`, `transform_queue.py`, or a shared
   utility can accidentally break the mapping's output. `pytest` + golden
   XMLs + `sensor.py` catch it in CI. Nothing in "just ask Claude" does.

3. **Cross-session, cross-engineer consistency.** Five engineers, five
   Claude sessions, five slightly different answers. One committed
   `.map.yaml` locks the answer. **The pipeline exists to freeze the answer
   once someone has decided it.**

4. **Institutional memory of the *why*.** The `trap:` field is a permanent
   record: "we didn't use `SUM_HANDLE_TIME` directly because AWS docs say it
   includes ACW." Six months from now the next engineer reads it and
   understands instantly. A chat log doesn't survive.

5. **A sign-off gate that means something.** `confirmed: true` is a human's
   signature. No LLM output is a signature — it's an opinion. Deploying to
   a customer needs the signature.

### The honest realization

You are **not** building:
- A "smarter mapping tool" (Claude is already smarter)
- An "AI pipeline" (the AI is the least valuable part)
- A "code generator" (formulas as YAML are declarative, not generated code)

You **are** building:
- A **domain ontology** — the authoritative shared vocabulary
- A **dialect corpus** — institutional memory of traps per vendor
- A **mapping runtime** — deterministic, cheap, auditable execution
- A **contract test suite** — regression protection
- A **drift sensor** — a check that runs without an LLM

These are **infrastructure**. Infrastructure looks like over-engineering
until you actually need it.

---

## Part 2 — How your operational reality sharpens the pitch

Your team builds ACD→WFM integrations. New customers or new ACD vendors
mean new integrations. Once built, mappings are stable — you don't touch
them unless the customer asks for something new.

That operational reality changes which arguments carry weight in the pitch:

### Weakens (be honest about this)

- **"Regression protection over time"** — weaker if the code never changes.
  Reframe as: "regression protection during the maintenance window that
  DOES happen (customer requests, vendor API upgrades, refactoring shared
  code)."
- **"Cross-engineer drift"** — weaker if few engineers touch a mapping.
  Reframe as: "when the original author leaves, the next person can pick
  up the mapping without a knowledge-transfer meeting."

### Strengthens (lean into these)

- **"New vendor onboarding is where the pain concentrates."** This IS your
  team's core recurring work. Every new ACD onboard = weeks of tribal
  knowledge extraction + debugging semantic traps that were already
  documented somewhere but nobody found them. Lexicon compresses this to
  hours-days by encoding the trap knowledge once and reusing it.
- **"Knowledge outlives the person."** Your team's real risk is the senior
  engineer who knows the Avaya/Genesys/Cisco traps by heart, and who
  eventually leaves. When they leave, the next new vendor takes 3× longer.
  Lexicon says: the vocabulary and the traps live in checked-in YAML, not
  in one person's head. **This is the compounding value.**
- **"AI is now writing enterprise integration code."** Even if your team
  doesn't use AI heavily today, the industry direction is that AI will.
  Lexicon prevents the AI from making silent, expensive semantic mistakes
  at scale. Framing this as "we're getting ahead of the wave" plays well
  at a Sparkathon.

---

## Part 3 — Sharpened Sparkathon pitch

### The one-sentence pitch

> "Every new ACD-to-WFM integration re-discovers the same semantic traps
> from scratch. Lexicon captures them once as an executable ubiquitous
> language, so onboarding a new vendor drops from weeks to days — and the
> knowledge survives the engineer."

### The demo (concrete, hard to argue with)

Two scenes, ~5 minutes:

**Scene 1 — "Without Lexicon" (the baseline pain, 2 min)**

- Show a fictional junior engineer asked to add Amazon Connect support.
- They open Claude, paste the AWS metrics page, ask "map to NICE".
- Claude produces a plausible-looking mapping. Show HandleTime = SUM_HANDLE_TIME.
- Ship it. Run against sample data. Numbers look right. Deploy.
- **Reveal the trap**: SUM_HANDLE_TIME includes ACW, so their HandleTime is
  10-20% too high. The customer's schedule is now over-staffed. Nobody
  notices for six weeks. Live-cost demonstration.

**Scene 2 — "With Lexicon" (the fix, 3 min)**

- Same junior engineer, same task, but now with Lexicon.
- They open the scaffolded dialect. Every canonical field has a `# TRAP:`
  marker. When they get to `HandleTime`, the trap is right there:
  "Amazon SUM_HANDLE_TIME includes ACW — subtract AFTER_CONTACT_WORK_TIME."
- They fill in the mapping. Contract test runs, hits the golden XML.
  Sensor runs, boundary_terms clean.
- Deploy. Numbers correct. **Time saved: 6 weeks of undetected error.**

**Optional Scene 3 — "Six months later" (institutional memory, 30 sec)**

- The junior engineer is gone. A new engineer maintains the integration.
- They open the dialect, read the trap, understand in 30 seconds.
- Contrast: without the dialect, they'd have to re-read AWS docs, guess,
  and probably re-introduce the bug.

### Why this demo wins

- **Concrete, single-screen numbers**: "Handle time 425 vs 480, off by 13%,
  causing over-staffing." Not vague productivity claims.
- **Universal narrative**: everyone in the room has seen a semantic bug ship
  because "the code compiles."
- **AI-aware**: shows why "just use Claude" isn't enough (Claude produces
  the wrong answer confidently in Scene 1).
- **Institutional angle**: Scene 3 addresses the actual pain of "senior
  engineer leaves, tribal knowledge evaporates" — a pain every enterprise
  understands.

### What NOT to demo

- Do NOT demo `automap.py` / `discover.py` / `scaffold_dialect.py`. These
  are helpers that either won't impress a Sparkathon judge or (worse) will
  make them ask "why isn't the AI doing more?" That's not the story you
  want.
- Do NOT demo the full pipeline end-to-end. Judges don't care about the
  pipeline; they care about the *outcome* (bug caught, weeks saved, junior
  engineer productive).
- Do NOT compare to Genesys/Avaya (already in the code). Use Amazon Connect
  or Cisco UCCE — vendors you're actively onboarding, so the demo is
  realistic, not staged.

---

## Part 4 — What to build/polish before Sparkathon

Prioritized so the highest-leverage work comes first.

### Must have (for the demo to work)

1. **Fill in Amazon Connect dialect** end-to-end with a real golden XML.
   Even 3 rows is enough. This is the concrete artifact the demo hangs on.
2. **One clear before/after script** — a shell script or notebook that runs
   Scene 1 (bad mapping, ships) then Scene 2 (Lexicon-guided, correct).
   Reproducible in 90 seconds.
3. **Sharpen `sensor.py`** — make its output punchy for the demo. Currently:
   "OK — no vocabulary drift". Change to something like "[sensor] ✓ 173
   AmazonConnect terms checked, 0 leaked into canonical output." Concrete
   numbers land better on a screen.
4. **Trap-highlight in dialect** — when the demo scrolls the dialect file,
   the `trap:` lines should be visually prominent. Consider syntax
   highlighting or a small viewer script.

### Nice to have (if time)

5. **Simplify `add_vendor.sh`** — cut the `discover.py`/`automap.py` steps
   from the demo path. Make the wrapper reflect the "just author the
   dialect and run tests" workflow.
6. **Add one more vendor** — Cisco UCCE or Five9. Shows the pattern
   generalizes. Even a partial dialect (2-3 canonical fields with traps)
   demonstrates reuse of the ontology.
7. **A one-page cheatsheet PDF** for the Sparkathon booth — "Lexicon in 60
   seconds" — for judges who don't sit through your full demo.

### Explicitly NOT worth doing before Sparkathon

- Full ontology of every WFM concept (occupancy, adherence, RONA, etc.).
  The current 15-ish concepts are enough to make the point. Complete
  ontology is Phase 3 work, per your original doc.
- LLM-based `discover.py` improvements. It's the wrong axis of investment.
- CI integration. Nice for production, distracting for the pitch.
- Multi-domain generalization (Phase 4 vision). Compelling in the pitch
  doc as future work, but do not attempt to build it for Sparkathon.

---

## Part 5 — Reframed pitch narrative

Original pitch line: **"Teach the agent your domain's language — then make
it enforceable."**

Sharper version for the new operational reality:

> **"Every ACD-to-WFM integration re-learns the same semantic traps.
> Lexicon captures them once — so agents write correct code, tests catch
> mistakes deterministically, and the knowledge outlives the engineer."**

Three-word tag: **capture, enforce, survive.**

- **Capture** the traps once (the dialect).
- **Enforce** them deterministically (contract tests + sensor).
- **Survive** engineer turnover, vendor API changes, and AI-generated code
  that would otherwise silently re-introduce the bugs.

---

## Part 6 — Answering the existential question

You asked: "am I really building something?"

Yes. But the thing you're building is not what the current code's shape
suggests. You are building:

- An **ontology + dialect corpus** — the closest thing your team has to a
  written-down conceptual model. This didn't exist before Lexicon.
- A **regression safety net** — golden XMLs + contract tests protect the
  business logic that your team's revenue depends on.
- A **succession-planning artifact** — when a senior engineer leaves,
  Lexicon means the next hire spends days-not-weeks getting productive.

Those are three real, ship-able business benefits. Not vague "AI is the
future" hand-waving.

The mistake is to think of Lexicon as "an AI-powered mapping tool." It
isn't. It's a **DDD ubiquitous language, made executable, with AI as an
accelerator during authoring**. The AI helps you author faster; the code
+ tests + sensor keep the artifact honest afterward.
