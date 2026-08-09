from lexicon.discover.enrich.semantic_tag import tag_fields, TAG_LEXICON
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def test_talk_time_like():
    fields = [_f("acdtime", "Talk time of ACD calls.")]
    tag_fields(fields)
    tags = {t.tag for t in fields[0].semantic_tags}
    assert "talk_time_like" in tags


def test_hold_time_like():
    fields = [_f("holdtime", "Time the caller was held.")]
    tag_fields(fields)
    assert any(t.tag == "hold_time_like" for t in fields[0].semantic_tags)


def test_acw_time_like():
    fields = [_f("acwtime", "After call work time.")]
    tag_fields(fields)
    assert any(t.tag == "acw_time_like" for t in fields[0].semantic_tags)


def test_ready_time_like():
    fields = [_f("i_readytime", "Time in ready/available state.")]
    tag_fields(fields)
    assert any(t.tag == "ready_time_like" for t in fields[0].semantic_tags)


def test_untagged_field_stays_untagged():
    fields = [_f("mystery", "Some field.")]
    tag_fields(fields)
    assert fields[0].semantic_tags == []


def test_multi_tag_with_weights():
    """A field mentioning both talk and hold should get both tags."""
    fields = [_f("total_talk_hold", "Combined talk plus hold time.")]
    tag_fields(fields)
    tags = {t.tag for t in fields[0].semantic_tags}
    assert "talk_time_like" in tags and "hold_time_like" in tags


def test_lexicon_covers_required_concepts():
    """Sanity check: the lexicon knows about every canonical concept family we need."""
    required = {
        "talk_time_like", "hold_time_like", "acw_time_like",
        "queue_delay_time_like", "ready_time_like", "not_ready_time_like",
        "login_time_like", "handled_total_like", "handled_within_sl_like",
        "abandoned_total_like", "abandoned_within_sl_like",
        "queue_key_like", "agent_key_like", "contacts_active_like",
    }
    assert required.issubset(set(TAG_LEXICON))
