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
