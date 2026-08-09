# Lexicon Integrity Layer — 2-minute Demo Video Script

A directed, beat-by-beat script for a single-take recording. Every beat has
its target duration, what appears on screen, what you type, and the exact
voiceover line.

---

## Recording setup

**Tools (Mac):**
- **Screen + audio:** ScreenStudio (paid, cleanest zoom + auto-cursor highlight)
  OR QuickTime Player (free — File → New Screen Recording, choose the internal mic)
  OR Loom (free tier fine for a 2-min clip; instant share link).
- **Terminal:** iTerm2 or macOS Terminal, font size bumped to ~18pt so it's
  readable at 720p. Dark background.
- **Editor:** VS Code / IntelliJ on the same monitor, one file open per beat.
- **Browser:** Streamlit UI at `http://localhost:8502/Integrity_Layer` in one tab.

**Layout for recording:**
Two windows tiled side-by-side or use one full-screen and Cmd-Tab between them.
Recommended: terminal on the left half, browser on the right half.

## Preparation checklist (run before you press record)

Run these once, close to record time, so the state is pristine:

```bash
cd /Users/Swapnil.Zade/Library/CloudStorage/OneDrive-NICELtd/Documents/Claude/Projects/Sparkathon\ 2026/Lexicon

# 1. Fresh warmed state — 22 days
rm -rf state/history state/baselines state/queue_registry out/*
python3 -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state

# 2. Confirm baseline
python3 -m pytest -q     # should say 82 passed
```

Also have ready:
- iTerm window at the project root, prompt visible.
- Browser tab at `http://localhost:8502/Integrity_Layer` (State should show "22 days in history").
- IDE file open: `docs/INTEGRITY_LAYER_EXPLAINER.md` (optional — cutaway only).

**Do a silent dry-run once.** Read the script aloud while clicking through
the beats. That gives you a feel for timing.

---

## Video structure — 6 beats, 120 seconds

| Beat | Time (s) | Screen | Voiceover intent |
|---|---|---|---|
| 1. Hook | 0:00 – 0:15 | Title card / IDE with problem | "There's a failure your transformer can't see." |
| 2. The blind spot | 0:15 – 0:35 | pytest + engine header | "The transformer is correct. That is the problem." |
| 3. Feature A | 0:35 – 1:05 | Terminal + data_health.json | "Baseline vs observed vs agent-system contradicts." |
| 4. Feature B | 1:05 – 1:35 | Terminal + identity_events.json | "Same agents, new key — probable rename." |
| 5. Ratify + Registry | 1:35 – 1:50 | Terminal + registry show | "Human approves. History stitched." |
| 6. Kicker | 1:50 – 2:00 | pytest -q green | "Zero changes to the transformer. 82 tests pass." |

---

## Beat 1 — Hook  (0:00 – 0:15,  15 seconds)

**On screen:** A simple title slide OR IDE showing
`docs/INTEGRITY_LAYER_EXPLAINER.md` scrolled to §1 "The problem in one paragraph".

Optional title-card text (make one in Keynote/Figma if you have 2 minutes to spare):

```
Lexicon
Integrity Layer

Catch the pipeline failures
your transformer cannot see.
```

**Voiceover (14 seconds, deliberate pacing):**

> *"When an Avaya CMS extract silently drops queue rows for an interval,
> your transformer does exactly what it should — it emits a valid, empty interval.
> WFM sees demand drop to zero. The forecast is quietly poisoned.
> No alarm. No test failure. The Lexicon Integrity Layer catches that."*

**Cut to Beat 2** at 0:15.

---

## Beat 2 — The blind spot  (0:15 – 0:35,  20 seconds)

**On screen:** Terminal. Show that the existing pipeline is healthy and correct.

**Type:**
```bash
pytest -q
```

Let it run to completion (~20s locally — start it right when you begin
speaking Beat 2 so the "82 passed" reveal lands at the end of your line).
If it's too slow to fit, use `pytest -q --no-header 2>&1 | tail -3` to only
show the summary line.

**Voiceover (18 seconds):**

> *"The transformer's mapping is expert-approved. Golden files, DTD contract,
> a sensor that catches vocabulary drift. All 82 tests pass. The output XML
> is byte-identical to the reference. Everything you can automate about
> 'correct' is already automated."*

Pause 1 second on the `82 passed` line so the viewer can read it.

**Voiceover — the pivot (2 seconds):**

> *"And still, this is not enough."*

**Cut to Beat 3** at 0:35.

---

## Beat 3 — Feature A (Completeness & Cause)  (0:35 – 1:05,  30 seconds)

**On screen:** Terminal. About to run the pipeline-gap scenario.

**Type (or paste — pre-copy to clipboard to save time):**
```bash
python3 -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/pipeline_gap/2025-07-14 \
    --customer demo --state-dir state \
    --out out/demo --run-date 2025-07-14
```

Result line prints. Then:

```bash
cat out/demo/data_health.json | python3 -m json.tool
```

Scroll (or hold Cmd+/ zoom) so the `findings` array is fully visible.

**Voiceover (28 seconds — sync tightly with the on-screen output):**

Beat 3a — while typing the first command (7 seconds):

> *"Feature A. Pipeline gap scenario. Twenty-two days of healthy history are already warmed. Day thirty-one has one interval missing from queue-CSV: split 44 at 09:30. Agents were staffed the whole time."*

Beat 3b — after `cat` shows the JSON (13 seconds):

> *"Baseline expected sixty contacts. Observed zero. Z-score minus thirty.
> Five agents were staffed and ready — the cross-report signal that pins
> the cause. Classification: queue-extract gap. Not a real drop.
> This finding goes in a sidecar JSON. The XML is untouched."*

Beat 3c — the payoff line (7 seconds):

> *"That contradiction is invisible to the transformer, invisible to the sensor,
> invisible to WFM. The integrity layer is the only place it becomes visible."*

**Cut to Beat 4** at 1:05.

---

## Beat 4 — Feature B (Queue Identity Resolution)  (1:05 – 1:35,  30 seconds)

**On screen:** Terminal.

**Type:**
```bash
rm -rf state/history state/baselines state/queue_registry
python3 -m src.integrity.run --warmup \
    --input fixtures/avaya_30d --customer demo --state-dir state
python3 -m src.integrity.run \
    --input fixtures/avaya_30d_scenarios/queue_renumber/2025-07-14 \
    --customer demo --state-dir state \
    --out out/demo --run-date 2025-07-14
cat out/demo/identity_events.json | python3 -m json.tool
```

Chain them with `&&` if you're comfortable — one paste, one Enter, less
dead air. Scroll to the `proposals` block.

**Voiceover (28 seconds):**

Beat 4a — while the warmup + run finish (10 seconds):

> *"Feature B. Same day, different story. The ACD has renumbered Sales
> from split 44 to split 47. Different vendor key. Same three agents."*

Beat 4b — after JSON appears (18 seconds):

> *"The layer proposes: 47 is queue-Q-44 renamed. Confidence 0.80.
> Agent-set overlap: one point zero. Same team. Same hours.
> The proposal is written to identity-events dot JSON — it never
> auto-applies. A human ratifies."*

**Cut to Beat 5** at 1:35.

---

## Beat 5 — Ratify + Registry  (1:35 – 1:50,  15 seconds)

**On screen:** Terminal.

**Type:**
```bash
python3 -m src.integrity.registry approve out/demo/identity_events.json \
    --proposal P-2025-07-14-RENAME-0 --customer demo --state-dir state
python3 -m src.integrity.registry show --customer demo --state-dir state | grep -A 3 Q-44
```

The second command isolates the Q-44 entry so the `aliases: [44, 47]` line
is the visual punchline.

**Voiceover (14 seconds):**

> *"Approve. The alias '47' is appended to canonical Q-44 in the registry.
> From this moment on, every day that sees split 47 rolls straight into
> Q-44's history. WFM sees one continuous queue. No discontinuity."*

**Cut to Beat 6** at 1:50.

---

## Beat 6 — The kicker  (1:50 – 2:00,  10 seconds)

**On screen:** Terminal.

**Type:**
```bash
pytest -q tests/test_integrity_isolation.py
```

This runs only the four regression-fence tests — fast (~3 s).

**Voiceover (9 seconds):**

> *"Everything I just did is additive. Not one byte of the transformer's
> XML changed. The engine, the sensor, all 82 tests — still green.
> Correct transform, plus integrity. Data WFM can trust."*

Let the terminal show `4 passed` for a beat, then fade to black or your
title card.

---

## Voiceover timing budget (word counts)

| Beat | Seconds | Approx words at 145 wpm |
|---|---|---|
| 1 Hook | 14 s | ~34 words ✅ (~40 in script — trim if needed) |
| 2 Blind spot | 20 s | ~48 words ✅ |
| 3 Feature A | 28 s | ~68 words ✅ |
| 4 Feature B | 28 s | ~68 words ✅ |
| 5 Ratify | 14 s | ~34 words ✅ |
| 6 Kicker | 9 s | ~22 words ✅ |
| **Total** | **113 s** | **~274 words** — leaves 7-second buffer |

If any beat runs long during your rehearsal, the safe cuts are:
- Beat 1: drop the "no test failure" line
- Beat 3b: shorten to "Baseline expected 60. Observed 0. Five agents staffed. Queue-extract gap."
- Beat 4b: drop the "same hours" line

## Delivery tips

- **Speak slower than feels natural.** 140-150 wpm is the sweet spot for a
  technical demo. Judge listeners assume you know what you're talking about
  when you deliberately pause on the payoff numbers.
- **Do not read the JSON aloud.** Say the interpretation. Let the viewer's
  eyes read the JSON while your voice explains.
- **Pause 1 full second after "82 tests pass" and after "aliases: [44, 47]".**
  These are the two visual punchlines. Silence sells them.
- **One take is fine.** Do not over-edit. A single confident take beats a
  polished but stitched-together video for a judged submission.

## Optional polish (if you have another 30 minutes)

- **Title card** at 0:00 and 2:00 (Keynote, 3-second fade).
- **Zoom-in on the key JSON fields** (`classification`, `confidence`,
  `agents_staffed`) using the recording tool's zoom-to-cursor feature.
- **On-screen captions** for the three payoff numbers:
  - `expected=60, observed=0, z=-30` at 0:55
  - `44 → 47, confidence 0.80` at 1:25
  - `aliases: [44, 47]` at 1:45
- **Background music** at very low volume (Epidemic Sound "clean tech" categories
  work well — but only if you're licensing legally).

## After recording

- Export at 1080p if the platform allows, 720p otherwise.
- Filename: `lexicon-integrity-layer-2min.mp4`
- Trim leading/trailing silence with QuickTime (Edit → Trim).
- Watch it once at 1.25× and once at 1× before submitting.

## Fallback: 60-second cut

If the submission limit turns out to be 60 seconds, collapse to three beats:
0:00-0:15 hook, 0:15-0:40 Feature A demo, 0:40-1:00 Feature B demo + ratify.
Skip Beat 2 (context) and Beat 6 (kicker); the terminal output IS the proof.

---

**End of script.** Good luck with the submission.
