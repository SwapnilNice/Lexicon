from pathlib import Path
import textwrap
import pytest

from lexicon.blueprints.parser import parse_blueprint, ParserError


def _write(tmp_path, body):
    p = tmp_path / "bp.md"
    p.write_text(textwrap.dedent(body).lstrip("\n"))
    return p


def test_parses_frontmatter_and_sections(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: salesforce
        routing_model: queue_based
        ---
        # Overview
        Words.

        # Prerequisites
        - Item 1
    """)
    bp = parse_blueprint(p)
    assert bp.frontmatter["platform"] == "salesforce"
    assert bp.frontmatter["routing_model"] == "queue_based"
    assert [h for h, _ in bp.sections] == ["Overview", "Prerequisites"]
    overview_body = dict(bp.sections)["Overview"].strip()
    assert overview_body == "Words."


def test_parses_event_subsections(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: salesforce
        ---
        # ACD event mapping

        ### interaction.received
        - **Recorded in:** `PSR`
        - **Trigger:** interaction arrives
        - **Prerequisite events:** none
        - **Caveats:** none

        ### interaction.routed
        - **Recorded in:** `AgentWork`
        - **Trigger:** router assigns
        - **Prerequisite events:** interaction.received
        - **Caveats:** none
    """)
    bp = parse_blueprint(p)
    assert set(bp.event_subsections.keys()) == {"interaction.received", "interaction.routed"}
    assert bp.event_subsections["interaction.received"]["Recorded in"] == "`PSR`"
    assert bp.event_subsections["interaction.routed"]["Prerequisite events"] == "interaction.received"


def test_missing_frontmatter_raises(tmp_path):
    p = _write(tmp_path, """
        # Overview
        No frontmatter here.
    """)
    with pytest.raises(ParserError, match="frontmatter"):
        parse_blueprint(p)


def test_malformed_frontmatter_yaml_raises(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: [salesforce
        ---
        # Overview
        Body.
    """)
    with pytest.raises(ParserError, match="YAML"):
        parse_blueprint(p)


def test_hash_inside_code_fence_not_treated_as_header(tmp_path):
    p = _write(tmp_path, """
        ---
        platform: salesforce
        ---
        # Overview

        Some content with a code block:

        ```python
        # This is a Python comment, not a section header.
        x = 1
        ```

        More overview text.
    """)
    bp = parse_blueprint(p)
    assert [h for h, _ in bp.sections] == ["Overview"]
