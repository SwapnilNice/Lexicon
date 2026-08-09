# Lexicon Guide — Avaya → NICE WFM **Queue** report (inbound voice)

> Read this BEFORE writing any transformation code. This is the ubiquitous
> language for the Queue report. Code in these canonical terms, not in Avaya terms.
> Media type in scope: **Immediate Response** (Avaya inbound voice / ACD).

## Golden rules (do not violate)

1. **HandleTime = talk + hold. Never add ACW.**
   `HandleTime = acdtime + holdtime`. Avaya `acdtime` is **talk only and
   EXCLUDES hold**, so you must ADD `holdtime`. After-call work (`acwtime`) goes
   to **WorkTime**, as its own field. Folding ACW into HandleTime is the #1
   silent bug — it inflates AHT and corrupts every downstream forecast.

2. **Every duration is total seconds**, wrapped as
   `<Field><duration><totalseconds>N</totalseconds></duration></Field>`.

3. **Every count** is wrapped as `<Field><count>N</count></Field>`, integer ≥ 0.

4. **QueueValue is the unique key** (1–100 ASCII chars). Use the Avaya skill/split
   (or VDN) number. It must be stable across intervals.

5. **Do not emit SvcLvlPct for inbound voice** — WFM derives service level itself
   from HandledShort/Long + AbandonedShort/Long. Emitting it is ignored at best,
   misleading at worst.

6. **Do not emit BackLog / RightParty / WrongParty** for inbound voice — not
   applicable to Immediate Response.

7. **No Avaya column names past the adapter boundary.** `acdtime`, `acwtime`,
   `holdtime`, `anstime`, `abncalls`, `acceptable`, `slvlabns`, `split`, `logid`
   must never appear in the canonical output or in canonical-layer code.
   Translate at the edge.

## Field-by-field mapping (Queue)

Source table: **hsplit** (split/skill intrahour). Columns are lowercase.

| Canonical | Avaya hsplit | Rule | Required (voice) |
|-----------|--------------|------|------------------|
| `QueueValue` | `split` | unique queue key | **required (key)** |
| `AbandonedShort` | `slvlabns` | abandons within SL | required if available |
| `AbandonedLong` | `abncalls − slvlabns` | abandons over SL (or total abncalls) | required if available |
| `HandledShort` | `acceptable` | answered within SL | required if available |
| `HandledLong` | `acdcalls − acceptable` | answered over SL (or total acdcalls) | **required** |
| `HandleTime` | **`acdtime + holdtime`** | talk + hold (acdtime EXCLUDES hold → add it) | **required** |
| `HoldTime` | `holdtime` | hold only | required if available |
| `WorkTime` | **`acwtime`** | ACW only | required if available |
| `QueueDelayTime` | `anstime` | queue + ring wait before answer | required if available |
| `ContactsActive` | derived | answered now, arrived earlier | required |

## Output shape (one QueueData block)

```xml
<QueueData>
  <QueueValue>5001</QueueValue>
  <AbandonedShort><count>2</count></AbandonedShort>
  <AbandonedLong><count>1</count></AbandonedLong>
  <HandledShort><count>40</count></HandledShort>
  <HandledLong><count>8</count></HandledLong>
  <HandleTime><duration><totalseconds>3120</totalseconds></duration></HandleTime>
  <HoldTime><duration><totalseconds>240</totalseconds></duration></HoldTime>
  <WorkTime><duration><totalseconds>600</totalseconds></duration></WorkTime>
  <QueueDelayTime><duration><totalseconds>480</totalseconds></duration></QueueDelayTime>
  <ContactsActive><count>1</count></ContactsActive>
</QueueData>
```

## Envelope & delivery

- Root `HistPlugin` → `DataSourceNode` → `Vendor` → `QueueNode` →
  `TimePeriod`(`DateTime` `CCYYMMDDThhmm`) → one or more `QueueData`.
- File name: `Q_MMDDYY.HHMM.xml` (HHMM = start of interval).
- Delivery dir: `/totalview/ftp/switches/customer<X>/<acdid#>/`.
- **Omit the DOCTYPE in production**; include it only when validating against
  `HistPlugin.dtd`.
