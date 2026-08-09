from pathlib import Path
import textwrap

from lexicon.blueprints.index import discover


def test_discovers_blueprint_files(tmp_path):
    (tmp_path / "salesforce").mkdir()
    (tmp_path / "salesforce" / "queue_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        routing_model: queue_based
        ---
        # Overview
    """))
    (tmp_path / "salesforce" / "skill_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        routing_model: skill_based
        ---
        # Overview
    """))
    found = discover(tmp_path)
    names = sorted(p.name for p in found)
    assert names == ["queue_based.md", "skill_based.md"]


def test_skips_files_without_platform_frontmatter(tmp_path):
    (tmp_path / "salesforce").mkdir()
    (tmp_path / "salesforce" / "queue_based.md").write_text(textwrap.dedent("""
        ---
        platform: salesforce
        ---
        # Overview
    """))
    (tmp_path / "salesforce" / "README.md").write_text("# Not a blueprint\nJust docs.\n")
    found = discover(tmp_path)
    assert [p.name for p in found] == ["queue_based.md"]


def test_returns_empty_on_missing_dir(tmp_path):
    assert discover(tmp_path / "does_not_exist") == []
