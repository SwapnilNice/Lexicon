from pathlib import Path
import json

import pytest
import yaml

from lexicon.discover.cache import DiskCache
from lexicon.discover.llm import LLMClient
from lexicon.discover.models import (
    RegistrySource, VendorRegistryEntry,
)
from lexicon.discover.pipeline import run_pipeline


AVAYA_MINI_HTML = """
<html><title>hsplit</title><body>
  <table>
    <tr><th>Field</th><th>Description</th></tr>
    <tr><td>split</td><td>Split/skill number, the queue key.</td></tr>
    <tr><td>acdtime</td><td>Talk time of ACD calls. Does NOT include holdtime.</td></tr>
    <tr><td>holdtime</td><td>Hold time on ACD calls, in seconds.</td></tr>
    <tr><td>acwtime</td><td>After call work time, in seconds.</td></tr>
    <tr><td>anstime</td><td>Delay before answer, in seconds.</td></tr>
    <tr><td>acdcalls</td><td>Count of handled ACD calls.</td></tr>
    <tr><td>acceptable</td><td>Count of ACD calls answered within the service level.</td></tr>
    <tr><td>abncalls</td><td>Count of abandoned calls.</td></tr>
    <tr><td>slvlabns</td><td>Count of abandons within the service level.</td></tr>
    <tr><td>contactsactive</td><td>Contacts active (carryover from previous interval).</td></tr>
  </table>
</body></html>
"""


def test_avaya_mini_pipeline_reproduces_expected_formulas(tmp_path):
    cache_dir = tmp_path / "cache"
    cache = DiskCache(cache_dir)
    cache.put("http", "https://mock.avaya/hsplit", AVAYA_MINI_HTML.encode())
    entry = VendorRegistryEntry(
        slug="avaya_cms_mini",
        name="Avaya CMS (mini fixture)",
        aliases=[],
        category="fixed_schema",
        description="mini",
        sources=[RegistrySource(
            kind="html_doc", role="primary",
            url="https://mock.avaya/hsplit",
            crawl={"max_depth": 0, "max_pages": 1},
        )],
    )
    llm = LLMClient(cache=cache, offline=True)   # must not need LLM for this fixture

    result = run_pipeline(
        entry=entry, cache=cache, llm=llm,
        catalogs_dir=tmp_path / "catalogs",
        proposed_dir=tmp_path / "proposed",
        reports_dir=tmp_path / "reports",
        report="queue",
    )

    prop_path = tmp_path / "proposed" / "avaya_cms_mini.queue.PROPOSED.yaml"
    proposed = yaml.safe_load(prop_path.read_text())
    fields = proposed["fields"]
    assert fields["QueueValue"] == "split"
    assert fields["HandleTime"] == "acdtime + holdtime"
    assert fields["WorkTime"] == "acwtime"
    assert fields["HoldTime"] == "holdtime"
    assert fields["HandledShort"] == "acceptable"
    assert fields["HandledLong"] == "acdcalls - acceptable"
    assert fields["AbandonedShort"] == "slvlabns"
    assert fields["AbandonedLong"] == "abncalls - slvlabns"

    # report file exists and is non-empty
    report_path = tmp_path / "reports" / "avaya_cms_mini.md"
    assert report_path.exists()
    assert "Discovery report" in report_path.read_text()

    # catalog exists
    catalog_path = tmp_path / "catalogs" / "avaya_cms_mini.yaml"
    assert catalog_path.exists()
