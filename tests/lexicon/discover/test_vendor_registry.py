from pathlib import Path
import textwrap
import pytest

from lexicon.discover.registry import load_registry, RegistryError


def _write(path: Path, body: str):
    path.write_text(textwrap.dedent(body))


def test_load_one_valid_entry(tmp_path):
    _write(tmp_path / "avaya_cms.yaml", """
        slug: avaya_cms
        name: "Avaya CMS"
        aliases: ["Avaya", "CMS Historical"]
        category: fixed_schema
        description: "d"
        sources:
          - kind: html_doc
            role: primary
            url: https://example.com/docs
            crawl:
              max_depth: 2
              max_pages: 30
    """)
    entries = load_registry(tmp_path)
    assert len(entries) == 1
    assert entries[0].slug == "avaya_cms"
    assert entries[0].sources[0].crawl["max_depth"] == 2


def test_missing_slug_raises(tmp_path):
    _write(tmp_path / "bad.yaml", """
        name: "Bad"
        category: fixed_schema
        description: "d"
        sources: []
        aliases: []
    """)
    with pytest.raises(RegistryError, match="slug"):
        load_registry(tmp_path)


def test_bad_category_raises(tmp_path):
    _write(tmp_path / "bad.yaml", """
        slug: bad
        name: "Bad"
        aliases: []
        category: not_a_category
        description: "d"
        sources: []
    """)
    with pytest.raises(RegistryError, match="category"):
        load_registry(tmp_path)


def test_empty_dir_returns_empty_list(tmp_path):
    assert load_registry(tmp_path) == []
