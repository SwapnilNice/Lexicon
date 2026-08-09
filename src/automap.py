"""
Lexicon AUTO-MAPPER  —  the AI "propose" step (step 2 of the workflow).

Reads:
  * the canonical ontology (what NICE fields mean, and which matter for this media)
  * a vendor field catalog (discovered from the vendor's docs) — name + description
Produces:
  * a PROPOSED dialect map (executable, engine-runnable) + confidence/rationale.

Two engines:
  --engine heuristic  (default, offline, deterministic) — name/keyword matcher.
      Deliberately proposes SINGLE-field guesses: it gets simple fields right and
      misses composites (HandleTime = talk + hold) and unit conversions (ms). That
      is the point — the harness then catches exactly those, and the expert fixes
      only the flagged ones.
  --engine llm  (real product path) — sends the catalog + ontology to an LLM and
      parses its proposed formulas. Requires an API key + SDK; documented, optional.

The proposal is NEVER trusted blindly: run verify_mapping.py to grade it against
the golden oracle, then a human approves. AI proposes, harness verifies, human ratifies.
"""
import argparse
import pathlib
import re
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANON = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())

# canonical tokens get expanded with domain synonyms so a name-matcher behaves
# like a plausible (but fallible) proposer.
SYN = {
    "handle": {"handle", "talk", "aht"},
    "handled": {"handle", "handled", "answer", "answered", "acd"},
    "work": {"work", "acw", "wrap", "after"},
    "delay": {"delay", "wait", "answer", "answered", "ans", "queue"},
    "abandoned": {"abandon", "abandoned", "abn"},
    "hold": {"hold", "held"},
    "active": {"active"},
    "queue": {"queue", "split", "skill"},
    "value": {"value", "id"},
    "contacts": {"contacts", "contact"},
    "short": {"short"},
    "long": {"long"},
    "time": {"time"},
}
STOP = {"of", "the", "in", "this", "a", "an", "and", "or", "to", "by", "all",
        "number", "ms", "t", "during", "interval"}


def tok(s: str):
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)          # split camelCase
    words = re.split(r"[^A-Za-z]+", s.lower())
    return {w for w in words if w and w not in STOP}


def expand(tokens):
    out = set()
    for t in tokens:
        out |= SYN.get(t, {t})
    return out


SECTION = {"queue": "queue", "agentqueue": "agent_queue", "agentsystem": "agent_system"}
AGENTQUEUE_TARGETS = ["QueueValue", "AgentValue", "Handled", "HandleTime", "HoldTime", "WorkTime"]
AGENTSYSTEM_TARGETS = ["AgentValue", "InternalContacts", "InternalHandleTime", "ReadyTime",
                       "NotReadyTime", "OutboundContacts", "OutboundHandleTime", "LoginTime"]


def target_fields(report="queue"):
    if report == "agentqueue":
        return AGENTQUEUE_TARGETS
    if report == "agentsystem":
        return AGENTSYSTEM_TARGETS
    # queue: canonical fields that matter for inbound voice (Immediate Response)
    fields = []
    for name, spec in CANON["queue"].items():
        req = (spec.get("media", {}) or {}).get("immediate_response", "not_required")
        if req in ("required", "required_if_available"):
            fields.append(name)
    return fields


def score(ctokens, vf, desc):
    """Name-substring match (strong) + description token overlap (weak)."""
    name = vf.lower()
    substr = sum(1 for t in ctokens if len(t) >= 3 and t in name)
    overlap = len(ctokens & (tok(vf) | tok(desc)))
    return substr * 3 + overlap


def propose_heuristic(catalog: dict, report="queue"):
    fields, proposals = {}, {}
    cat = catalog["fields"]
    cat_order = list(cat.keys())
    for cf in target_fields(report):
        ctokens = expand(tok(cf))            # canonical NAME tokens (+ domain synonyms)
        best, best_score = None, 0
        for vf in cat_order:                 # ties broken by catalog order
            sc = score(ctokens, vf, cat[vf])
            if sc > best_score:
                best, best_score = vf, sc
        if best is None:
            proposals[cf] = {"proposed": None, "confidence": 0.0,
                             "rationale": "no vendor field matched", "needs_review": True}
            continue
        conf = round(min(1.0, best_score / 8.0), 2)
        fields[cf] = best                      # SINGLE field — may miss arithmetic/units on purpose
        proposals[cf] = {
            "proposed": best,
            "confidence": conf,
            "rationale": f"best name/keyword match to '{best}'",
            "needs_review": conf < 0.6,
        }
    return fields, proposals


# ==========================================================================
# REFERENCE engine — reuse the formula PATTERNS learned from already-approved
# vendors. This is the "used existing vendors as reference" capability: instead
# of guessing a single field, it instantiates known composite patterns
# (HandleTime = talk + hold; Long = total - withinSL; ms -> /1000) by matching
# ROLES to the new vendor's fields. It avoids traps a naive matcher falls for.
# ==========================================================================
ROLE_KEYWORDS = {
    "key":           {"csq", "split", "skill", "queue", "vdn", "gate", "id", "name", "queueid"},
    "handled_total": {"handled", "acd", "answered", "acdcalls", "nhandled"},
    "handled_sl":    {"within", "sl", "acceptable", "servicelevel", "withinsl"},
    "abandon_total": {"abandoned", "abandon", "abn", "abncalls", "nabandoned"},
    "abandon_sl":    {"within", "sl", "slvl", "slvlabns", "servicelevel"},
    "talk":          {"talk", "acdtime", "ttalk"},
    "hold":          {"hold", "held", "holdtime", "theld"},
    "acw":           {"acw", "work", "wrap", "after", "acwtime", "tacw", "worktime"},
    "wait":          {"wait", "answer", "ans", "delay", "anstime", "queuetime", "tanswered", "tanswer", "queue"},
    "active":        {"active", "contactsactive"},
    # agent-report roles
    "agent_key":     {"logid", "userid", "agent", "extension", "agentid", "user"},
    "internal_count":{"internal", "da", "directagent", "internalcontacts", "daacdcalls", "ninternal"},
    "internal_time": {"internal", "internalhandletime", "daacdtime", "tinternal"},
    "ready":         {"ready", "avail", "available", "availtime", "idle", "iavailtime", "tidle"},
    "notready":      {"notready", "aux", "auxtime", "tiauxtime", "away", "notresponding"},
    "outbound_count":{"outbound", "oacdcalls", "outboundcontacts", "oacd", "noutbound"},
    "outbound_time": {"outbound", "oacdtime", "outboundhandletime", "toutbound"},
    "login":         {"login", "staff", "stafftime", "loggedin", "istafftime", "logintime", "tactive"},
}
TEMPLATES = {   # canonical field -> (combiner, [roles])   — derived from approved vendor maps
    "QueueValue":     ("key",    ["key"]),
    "AgentValue":     ("key",    ["agent_key"]),
    "HandledShort":   ("single", ["handled_sl"]),
    "HandledLong":    ("diff",   ["handled_total", "handled_sl"]),
    "AbandonedShort": ("single", ["abandon_sl"]),
    "AbandonedLong":  ("diff",   ["abandon_total", "abandon_sl"]),
    "HandleTime":     ("sum",    ["talk", "hold"]),
    "HoldTime":       ("single", ["hold"]),
    "WorkTime":       ("single", ["acw"]),
    "QueueDelayTime": ("single", ["wait"]),
    "ContactsActive": ("single", ["active"]),
    "Handled":        ("single", ["handled_total"]),
    "InternalContacts":   ("single", ["internal_count"]),
    "InternalHandleTime": ("single", ["internal_time"]),
    "ReadyTime":          ("single", ["ready"]),
    "NotReadyTime":       ("single", ["notready"]),
    "OutboundContacts":   ("single", ["outbound_count"]),
    "OutboundHandleTime": ("single", ["outbound_time"]),
    "LoginTime":          ("single", ["login"]),
}


# each role must contain its BASE concept (matched by token OR name-substring)
REQUIRE_BASE = {
    "handled_sl":     {"handled", "acd", "answered", "acceptable"},
    "handled_total":  {"handled", "acd", "answered"},
    "abandon_sl":     {"abandon", "abandoned", "abn"},
    "abandon_total":  {"abandon", "abandoned", "abn"},
    "internal_count": {"internal", "da"},
    "internal_time":  {"internal", "da"},
    "outbound_count": {"outbound"},
    "outbound_time":  {"outbound"},
    "ready":          {"ready", "avail", "idle"},
    "notready":       {"notready", "aux", "notresponding"},
    "login":          {"login", "staff", "active"},
}
DURATION_ROLES = {"talk", "hold", "acw", "wait", "ready", "notready", "login", "internal_time", "outbound_time"}
COUNT_ROLES = {"handled_total", "handled_sl", "abandon_total", "abandon_sl",
               "internal_count", "outbound_count", "active", "handled"}


def _base_ok(base, ftoks, name):
    return bool(base & ftoks) or any(b in name for b in base if len(b) >= 3)


def role_match(role, catalog):
    best, best_s = None, 0
    for vf, desc in catalog["fields"].items():
        name = vf.lower()
        ftoks = tok(vf) | tok(desc)
        kw = ROLE_KEYWORDS[role]
        base = REQUIRE_BASE.get(role)
        if base and not _base_ok(base, ftoks, name):
            continue
        s = len(kw & ftoks) + sum(1 for k in kw if len(k) >= 3 and k in name)
        sl_signal = bool({"within", "sl", "acceptable", "servicelevel"} & ftoks)
        if role.endswith("_sl") and not sl_signal:
            continue
        if role.endswith("_total") and sl_signal:
            s -= 5
        has_time = ("time" in ftoks) or name.endswith("time") or name.endswith("_ms")
        if role in DURATION_ROLES:
            s += 2 if has_time else -1              # prefer a duration field
        if role in COUNT_ROLES and has_time:
            s -= 2                                  # a count role should not pick a duration
        if s > best_s:
            best, best_s = vf, s
    return best, best_s


def _operand(field, unit):
    if unit == "duration_seconds" and field.endswith("_ms"):
        return f"{field} / 1000"
    return field


def reference_vendors():
    d = ROOT / "ontology" / "mappings"
    return sorted({f.stem.split(".")[0].title() for f in d.glob("*.map.yaml")})


def propose_reference(catalog: dict, report="queue"):
    fields, proposals = {}, {}
    section = SECTION[report]
    for cf in target_fields(report):
        unit = CANON[section][cf].get("unit", "count")
        combiner, roles = TEMPLATES.get(cf, ("single", []))
        matched = [role_match(r, catalog) for r in roles]
        if all(m[0] and m[1] > 0 for m in matched):
            names = [m[0] for m in matched]
            if combiner == "key":
                expr = names[0]
            elif combiner == "single":
                expr = _operand(names[0], unit)
            elif combiner == "sum":
                expr = f"{_operand(names[0], unit)} + {_operand(names[1], unit)}"
            elif combiner == "diff":
                expr = f"{_operand(names[0], unit)} - {_operand(names[1], unit)}"
            fields[cf] = expr
            proposals[cf] = {"proposed": expr, "confidence": 0.85,
                             "rationale": f"reused pattern {cf}={combiner}{roles} learned from approved vendors",
                             "needs_review": False}
        else:
            # fall back to a naive single-field guess and flag it
            ctokens = expand(tok(cf))
            best, bs = None, 0
            for vf in catalog["fields"]:
                sc = score(ctokens, vf, catalog["fields"][vf])
                if sc > bs:
                    best, bs = vf, sc
            if best:
                fields[cf] = best
            proposals[cf] = {"proposed": best, "confidence": round(min(1.0, bs / 8.0), 2),
                             "rationale": "no known pattern matched — naive name guess",
                             "needs_review": True}
    return fields, proposals


def propose_llm(catalog: dict, vendor: str, report="queue"):
    """Real product path. Builds a prompt and calls an LLM if available."""
    prompt = build_llm_prompt(catalog, vendor, report)
    try:
        import os
        import anthropic  # type: ignore
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-sonnet-5", max_tokens=2000,
            messages=[{"role": "user", "content": prompt}])
        text = msg.content[0].text
        data = yaml.safe_load(text)
        return data["fields"], data.get("proposals", {})
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            f"[automap] LLM engine unavailable ({e}).\n"
            f"Install `anthropic` and set ANTHROPIC_API_KEY, or use --engine heuristic.\n"
            f"--- prompt that would be sent ---\n{prompt}")


def build_llm_prompt(catalog: dict, vendor: str, report="queue") -> str:
    section = SECTION[report]
    canon_lines = []
    for cf in target_fields(report):
        s = CANON[section][cf]
        canon_lines.append(f"- {cf} ({s.get('unit')}): {s.get('definition','')}"
                           + (f"  TRAP: {s['trap']}" if s.get("trap") else ""))
    cat_lines = [f"- {k}: {v}" for k, v in catalog["fields"].items()]
    return (
        f"You are mapping {vendor} fields to a canonical WFM model.\n"
        f"For each canonical field, output an arithmetic formula over the vendor "
        f"fields (you may add, subtract, divide — e.g. for unit conversion).\n\n"
        f"CANONICAL FIELDS (target):\n" + "\n".join(canon_lines) +
        f"\n\nVENDOR FIELDS ({vendor}):\n" + "\n".join(cat_lines) +
        f"\n\nReturn YAML with keys `fields` (canonical -> formula string) and "
        f"`proposals` (canonical -> {{confidence, rationale, needs_review}}). "
        f"Watch units and composite definitions.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("catalog")
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--engine", choices=["heuristic", "reference", "llm", "lexicon"], default="reference")
    ap.add_argument("--report", choices=["queue", "agentqueue", "agentsystem"], default="queue")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    catalog = yaml.safe_load(pathlib.Path(args.catalog).read_text())
    if args.engine == "lexicon":
        from lexicon.discover.enrich.semantic_tag import tag_fields
        from lexicon.discover.enrich.trap_detect import detect_traps
        from lexicon.discover.enrich.unit_infer import infer_units
        from lexicon.discover.mapper import propose_mapping
        from lexicon.discover.models import EnrichedField, FieldSource, SemanticTag, Trap
        cat_fields = catalog.get("fields", {})
        enriched: list[EnrichedField] = []
        for name, spec in cat_fields.items():
            if isinstance(spec, str):        # legacy discover catalog: name -> description
                spec = {"description": spec}
            enriched.append(EnrichedField(
                name=name,
                description=spec.get("description", ""),
                sources=[FieldSource(doc_id="catalog", url="", locator="", snippet="")],
                unit=spec.get("unit", "unknown"),
                unit_confidence=float(spec.get("unit_confidence", 0.0)),
                semantic_tags=[SemanticTag(tag=t["tag"], weight=float(t.get("weight", 0.0)))
                               for t in (spec.get("semantic_tags") or [])],
                traps=[Trap(kind=t.get("kind", ""), target=t.get("target", ""),
                            evidence=t.get("evidence", ""))
                       for t in (spec.get("traps") or [])],
            ))
        # Rich catalog: use provided enrichment as-is.
        # Legacy catalog (only descriptions): populate enrichment now.
        if not any(e.unit != "unknown" for e in enriched):
            infer_units(enriched)
            tag_fields(enriched)
            detect_traps(enriched)
        proposed = propose_mapping(enriched, report=args.report)
        fields = {name: p.formula for name, p in proposed.items() if p.formula is not None}
        proposals = {
            name: {
                "proposed": p.formula,
                "confidence": p.confidence,
                "rationale": p.rationale,
                "needs_review": p.needs_review,
            }
            for name, p in proposed.items()
        }
    elif args.engine == "llm":
        fields, proposals = propose_llm(catalog, args.vendor, args.report)
    elif args.engine == "heuristic":
        fields, proposals = propose_heuristic(catalog, args.report)
    else:
        refs = [v for v in reference_vendors() if v.lower() != args.vendor.lower()]
        print(f"[automap:reference] reusing formula patterns learned from: {', '.join(refs) or '(none yet)'}")
        fields, proposals = propose_reference(catalog, args.report)

    doc = {
        "meta": {"vendor": args.vendor, "report": args.report, "status": "proposed",
                 "engine": args.engine},
        "fields": fields,
        "proposals": proposals,
    }
    text = ("# AUTO-PROPOSED mapping — NOT yet approved. Run verify_mapping.py, then\n"
            "# have an expert review. AI proposes, harness verifies, human ratifies.\n"
            + yaml.safe_dump(doc, sort_keys=False))
    out = args.out or str(ROOT / "ontology" / "proposed" / f"{args.vendor.lower()}.{args.report}.PROPOSED.yaml")
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(out).write_text(text)
    n_review = sum(1 for p in proposals.values() if p["needs_review"])
    print(f"[automap:{args.engine}] proposed {len(fields)} fields "
          f"({n_review} low-confidence) -> {out}")


if __name__ == "__main__":
    main()
