from pathlib import Path

from lexicon.discover.registry import load_registry

ROOT = Path(__file__).resolve().parents[3]


def test_seed_registry_has_avaya_and_genesys():
    entries = load_registry(ROOT / "ontology" / "registry")
    slugs = {e.slug for e in entries}
    assert "avaya_cms" in slugs
    assert "genesys_cloud" in slugs


def test_avaya_cms_has_primary_html_source():
    entries = load_registry(ROOT / "ontology" / "registry")
    avaya = next(e for e in entries if e.slug == "avaya_cms")
    primary_html = [s for s in avaya.sources if s.kind == "html_doc" and s.role == "primary"]
    assert primary_html, "avaya_cms needs at least one primary html_doc source"
    assert primary_html[0].url is not None and primary_html[0].url.startswith("https://")
