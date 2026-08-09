# Cross-vendor cheat sheet — the same canonical concept, two dialects

The canonical ontology is the anchor. Each vendor maps to it **differently**.
This is the clearest proof that meaning lives in the ontology, not the vendor.

## HandleTime — same NICE concept, opposite vendor rules

NICE canonical: **`HandleTime = talk + hold`** (after-call work is separate → `WorkTime`).

| Vendor | Source (verified) | Rule to reach NICE HandleTime | The trap |
|--------|-------------------|-------------------------------|----------|
| **Avaya CMS** (hsplit) | `acdtime` (talk, EXCLUDES hold), `holdtime`, `acwtime` | `acdtime + holdtime` | You must **ADD** holdtime, and **NOT add** acwtime |
| **Genesys Cloud** | `tTalk`, `tHeld`, `tAcw`, `tHandle` (all ms) | `(tTalk + tHeld) / 1000` | `tHandle` already **includes** ACW, and it's in **ms** |

So for the identical target field, the direction is opposite:
- **Avaya:** you must **ADD** hold to talk (acdtime excludes it), and exclude ACW.
- **Genesys:** you must **SUBTRACT** ACW (avoid `tHandle`) **and** convert ms→s.

That is the whole point: "handle time" is the same NICE concept, but the vendor
arithmetic to reach it is opposite. Only the ontology knows the true target.

A generic agent, given the vendor's own field named "handle time," maps it
straight across in both cases — and is wrong in both, for opposite reasons.

## Units

| Vendor | Duration unit | Action |
|--------|---------------|--------|
| Avaya CMS | seconds | none |
| Genesys Cloud | milliseconds | divide by 1000 |

## Keys

| Canonical | Avaya | Genesys |
|-----------|-------|---------|
| `QueueValue` | `split` (skill) | `queueId` |
| `AgentValue` | `logid` | `userId` |

Everything past the adapter boundary must be canonical. No `acwtime`, no
`tHandle`, no `_ms`, no `queueId` in the output.
