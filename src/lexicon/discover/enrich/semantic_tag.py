"""Semantic tagging: label each enriched field with the canonical concept
families it looks like (talk_time_like, hold_time_like, ready_time_like, …).

This is deliberately rule-based: a small hand-curated lexicon of vendor-agnostic
keywords + a substring/token matcher. The lexicon was seeded from the existing
src/automap.py ROLE_KEYWORDS table (which already worked for Avaya + Genesys),
generalized to a "*_like" naming scheme so it can be extended per canonical concept.
"""
from __future__ import annotations
import re

from ..models import EnrichedField, SemanticTag


# TAG_LEXICON is match-vocabulary ONLY.
#
# The keyword lists below contain vendor-specific tokens (Avaya's "acdtime",
# Genesys's "tTalk", etc.) so the tagger can recognize them in field names
# and descriptions. These tokens are NEVER emitted:
#   - `SemanticTag.rationale` is a synthetic string ("keyword lexicon match
#     (score=X)"), not a copy of the matched keyword.
#   - The vendor field names that DO appear in `PROPOSED.yaml` (rationale
#     strings like "composed from ['acdtime', 'holdtime']") come from the
#     enriched fields extracted from vendor docs — which is exactly what a
#     mapping file must say. That is not the "canonical output" CLAUDE.md
#     rule 4 restricts (that rule scopes to the WFM Import History XML that
#     `engine.py` produces).
TAG_LEXICON: dict[str, set[str]] = {
    # duration concepts
    "talk_time_like":       {"talk", "acdtime", "ttalk", "converse"},
    "hold_time_like":       {"hold", "held", "holdtime", "theld", "park"},
    "acw_time_like":        {"acw", "wrap", "wrapup", "aftercall", "after_call",
                             "aftercontactwork", "after_contact_work",
                             "worktime", "tacw", "acwtime"},
    "queue_delay_time_like": {"delay", "wait", "answered", "ans", "anstime",
                              "queuetime", "tanswered", "queue_time"},
    "ready_time_like":       {"ready", "avail", "available", "availtime", "idle",
                              "iavailtime", "tidle", "readytime"},
    "not_ready_time_like":   {"notready", "not_ready", "aux", "auxtime",
                              "tiauxtime", "away", "notresponding"},
    "login_time_like":       {"login", "staff", "stafftime", "loggedin",
                              "istafftime", "logintime", "tactive"},
    "internal_time_like":    {"internal_time", "daacdtime", "tinternal",
                              "internalhandletime"},
    "outbound_time_like":    {"outbound_time", "oacdtime", "toutbound",
                              "outboundhandletime"},
    "right_party_time_like": {"rpc_time", "righthandletime"},

    # count concepts
    "handled_total_like":       {"handled", "acd", "acdcalls", "nhandled",
                                 "answered", "nanswered"},
    "handled_within_sl_like":   {"acceptable", "within_sl", "withinsl",
                                 "servicelevel", "handled_sl", "sl_handled"},
    "abandoned_total_like":     {"abandoned", "abandon", "abn", "abncalls",
                                 "nabandoned"},
    "abandoned_within_sl_like": {"slvlabns", "sl_abandoned", "within_sl_abandoned"},
    "contacts_active_like":     {"contactsactive", "active", "carryover"},
    "internal_count_like":      {"internal_contacts", "internalcontacts",
                                 "daacdcalls", "ninternal"},
    "outbound_count_like":      {"outbound_contacts", "outboundcontacts",
                                 "oacdcalls", "noutbound"},

    # keys
    "queue_key_like":  {"csq", "split", "skill", "queueid", "queue_id", "vdn", "gate"},
    "agent_key_like":  {"logid", "userid", "agent", "extension", "agentid"},
}


_TOKEN_RE = re.compile(r"[^A-Za-z]+")


def _tokens(name: str, desc: str) -> set[str]:
    parts = _TOKEN_RE.split(name.lower())
    parts += _TOKEN_RE.split(desc.lower())
    return {p for p in parts if p}


def _score_tag(tag: str, keywords: set[str], name: str, desc: str, toks: set[str]) -> float:
    name_l = name.lower()
    substr = sum(1 for kw in keywords if len(kw) >= 4 and kw in name_l)
    token = len(keywords & toks)
    if substr == 0 and token == 0:
        return 0.0
    raw = 3 * substr + token
    return min(1.0, raw / 5.0)


def tag_fields(fields: list[EnrichedField]) -> None:
    for f in fields:
        toks = _tokens(f.name, f.description)
        for tag, kws in TAG_LEXICON.items():
            s = _score_tag(tag, kws, f.name, f.description, toks)
            if s >= 0.4:
                f.semantic_tags.append(SemanticTag(
                    tag=tag,
                    weight=s,
                    rationale=f"keyword lexicon match (score={s:.2f})",
                ))
