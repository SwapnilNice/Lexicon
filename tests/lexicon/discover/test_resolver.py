from pathlib import Path
import textwrap
import pytest

from lexicon.discover.registry import load_registry
from lexicon.discover.resolver import resolve_vendor, ResolveError, ResolveResult


def _mk(tmp_path, files):
    for name, body in files.items():
        (tmp_path / name).write_text(textwrap.dedent(body))
    return load_registry(tmp_path)


def _entry(slug, name, aliases):
    return f"""
        slug: {slug}
        name: "{name}"
        aliases: {aliases!r}
        category: fixed_schema
        description: d
        sources: []
    """


def test_exact_slug_match(tmp_path):
    reg = _mk(tmp_path, {"avaya_cms.yaml": _entry("avaya_cms", "Avaya CMS", ["Avaya"])})
    r = resolve_vendor("avaya_cms", reg)
    assert isinstance(r, ResolveResult)
    assert r.entry.slug == "avaya_cms"
    assert r.resolved_via == "slug"


def test_exact_name_match(tmp_path):
    reg = _mk(tmp_path, {"avaya_cms.yaml": _entry("avaya_cms", "Avaya CMS", ["Avaya"])})
    assert resolve_vendor("Avaya CMS", reg).resolved_via == "name"


def test_alias_match(tmp_path):
    reg = _mk(tmp_path, {"avaya_cms.yaml": _entry("avaya_cms", "Avaya CMS", ["Avaya", "CMS"])})
    assert resolve_vendor("CMS", reg).resolved_via == "alias"


def test_case_insensitive(tmp_path):
    reg = _mk(tmp_path, {"avaya_cms.yaml": _entry("avaya_cms", "Avaya CMS", ["Avaya"])})
    assert resolve_vendor("AVAYA CMS", reg).entry.slug == "avaya_cms"


def test_multiple_matches_raises_with_candidates(tmp_path):
    reg = _mk(tmp_path, {
        "avaya_cms.yaml":   _entry("avaya_cms",   "Avaya CMS",   ["Avaya"]),
        "avaya_aura.yaml":  _entry("avaya_aura",  "Avaya Aura",  ["Avaya"]),
    })
    with pytest.raises(ResolveError) as ei:
        resolve_vendor("Avaya", reg)
    assert "avaya_cms" in str(ei.value) and "avaya_aura" in str(ei.value)


def test_no_match_raises(tmp_path):
    reg = _mk(tmp_path, {"avaya_cms.yaml": _entry("avaya_cms", "Avaya CMS", [])})
    with pytest.raises(ResolveError, match="no match"):
        resolve_vendor("nice_cxone", reg)


# ---------------------------------------------------------------------------
# Task 8 – search fallback for unknown vendors
# ---------------------------------------------------------------------------

from lexicon.discover.cache import DiskCache
from lexicon.discover.llm import LLMClient
from lexicon.discover.resolver import resolve_vendor_with_fallback


def test_search_fallback_returns_synthetic_entry(tmp_path):
    cache = DiskCache(tmp_path / "cache")
    prompt_key = None

    def fake_llm(model, prompt):
        nonlocal prompt_key
        prompt_key = (model, prompt)
        return (
            "slug: acme_cx\n"
            "name: Acme CX\n"
            "sources:\n"
            "  - kind: html_doc\n"
            "    role: primary\n"
            "    url: https://docs.acme.example/reference\n"
        )

    llm = LLMClient(cache=cache, offline=False, _call_impl=fake_llm)
    result = resolve_vendor_with_fallback("Acme CX", registry=[], llm=llm)
    assert result.resolved_via == "search"
    assert result.entry.slug == "acme_cx"
    assert result.entry.sources[0].url.startswith("https://docs.acme.example")
    # prompt should mention the vendor name
    assert "Acme CX" in prompt_key[1]


def test_search_fallback_prefers_registry_when_present(tmp_path):
    import textwrap
    (tmp_path / "avaya_cms.yaml").write_text(textwrap.dedent("""
        slug: avaya_cms
        name: "Avaya CMS"
        aliases: []
        category: fixed_schema
        description: d
        sources: []
    """))
    from lexicon.discover.registry import load_registry
    reg = load_registry(tmp_path)
    def boom(model, prompt):
        raise AssertionError("should not have called LLM")
    llm = LLMClient(cache=DiskCache(tmp_path / "cache"),
                    offline=False, _call_impl=boom)
    r = resolve_vendor_with_fallback("Avaya CMS", registry=reg, llm=llm)
    assert r.resolved_via == "name"


def test_search_fallback_offline_raises_when_registry_misses(tmp_path):
    llm = LLMClient(cache=DiskCache(tmp_path / "cache"), offline=True)
    with pytest.raises(Exception, match="cache miss"):
        resolve_vendor_with_fallback("Unknown Vendor", registry=[], llm=llm)


def test_search_fallback_rejects_unsafe_slug(tmp_path):
    cache = DiskCache(tmp_path / "cache")

    def fake_llm(model, prompt):
        return (
            "slug: ../evil\n"
            "name: Evil\n"
            "sources:\n"
            "  - kind: html_doc\n"
            "    role: primary\n"
            "    url: https://x/y\n"
        )

    llm = LLMClient(cache=cache, offline=False, _call_impl=fake_llm)
    from lexicon.discover.resolver import ResolveError
    with pytest.raises(ResolveError, match="unsafe slug"):
        resolve_vendor_with_fallback("Evil", registry=[], llm=llm)


def test_search_prompt_accepts_community_sites():
    """The prompt must not restrict URLs to `docs.*/developer.*` — community sites
    (community.*, success.*, support.*, trailhead.*, kb.*) hold real integration
    docs for many vendors (Five9 WSDL articles, Salesforce Trailhead, etc.)."""
    from lexicon.discover.resolver import SEARCH_PROMPT_TEMPLATE
    prompt = SEARCH_PROMPT_TEMPLATE.format(vendor="TestVendor")
    for domain_pattern in ("community.", "support."):
        assert domain_pattern in prompt, (
            f"Search prompt must mention '{domain_pattern}' as a valid source domain"
        )


def test_search_fallback_accepts_community_url_from_llm(tmp_path):
    """End-to-end: if the LLM returns a community URL, it is accepted as a valid source."""
    cache = DiskCache(tmp_path / "cache")

    def fake_llm(model, prompt):
        return (
            "slug: five9_test\n"
            "name: Five9\n"
            "sources:\n"
            "  - kind: html_doc\n"
            "    role: primary\n"
            "    url: https://community.five9.com/s/article/API-WSDL-file-used-by-Five9\n"
        )

    llm = LLMClient(cache=cache, offline=False, _call_impl=fake_llm)
    r = resolve_vendor_with_fallback("Five9", registry=[], llm=llm)
    assert r.entry.slug == "five9_test"
    assert r.entry.sources[0].url.startswith("https://community.five9.com")
