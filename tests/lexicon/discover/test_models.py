from lexicon.discover.models import (
    SourceDoc, RawField, FieldSource, EnrichedField, SemanticTag,
    Trap, ProposedField, VendorRegistryEntry, RegistrySource,
)


def test_source_doc_roundtrip():
    d = SourceDoc(
        id="page:1", kind="html",
        url="https://x.example/y",
        title="Y",
        content="<p>hi</p>",
        text="hi",
    )
    assert d.id == "page:1"
    assert d.kind == "html"


def test_raw_field_defaults():
    r = RawField(
        name="acdtime",
        description="Talk time of all ACD calls.",
        source=FieldSource(doc_id="page:1", url="https://x.example",
                           locator="table > tr:nth-child(3)",
                           snippet="ACDTIME — Talk time..."),
        extractor="html_structured",
        confidence_extraction=0.98,
    )
    assert r.name == "acdtime"


def test_enriched_field_merges_sources():
    f = EnrichedField(
        name="acdtime",
        description="Talk time.",
        sources=[
            FieldSource(doc_id="page:1", url="u1", locator="l1", snippet="s1"),
            FieldSource(doc_id="page:2", url="u2", locator="l2", snippet="s2"),
        ],
        unit="duration_seconds",
        unit_confidence=0.9,
        unit_signals=["description_regex"],
        semantic_tags=[SemanticTag(tag="talk_time_like", weight=0.95, rationale="explicit talk")],
        traps=[Trap(kind="exclusion", target="hold_time", evidence="does NOT include holdtime")],
    )
    assert len(f.sources) == 2
    assert f.semantic_tags[0].tag == "talk_time_like"


def test_proposed_field_shape():
    p = ProposedField(
        formula="acdtime + holdtime",
        confidence=0.88,
        rationale="Compositional: talk+hold",
        alternates=[],
        needs_review=False,
    )
    assert p.formula == "acdtime + holdtime"


def test_vendor_registry_entry_shape():
    e = VendorRegistryEntry(
        slug="avaya_cms",
        name="Avaya CMS",
        aliases=["Avaya", "CMS Historical"],
        category="fixed_schema",
        description="d",
        sources=[RegistrySource(kind="html_doc", role="primary",
                                url="https://x", crawl={"max_depth": 2})],
    )
    assert e.slug == "avaya_cms"
    assert e.category == "fixed_schema"
