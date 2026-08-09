"""E2E regression: Genesys Cloud analytics snapshot → discover pipeline → correct mapping.

Punchlines:
  (a) ms→s unit conversion embedded in the formula (all duration fields use / 1000).
  (b) HandleTime composed from tTalk + tHeld, NOT from the vendor's tHandle field
      which includes ACW (wrap-up).

Uses a committed HTML snapshot (fixtures/vendor_docs_snapshots/genesys_cloud/analytics.html)
as input, runs the full offline pipeline, and asserts the punchline acceptance criteria.
No network calls; no LLM cost in CI.
"""
from pathlib import Path
import yaml

from lexicon.discover.cache import DiskCache
from lexicon.discover.llm import LLMClient
from lexicon.discover.models import RegistrySource, VendorRegistryEntry
from lexicon.discover.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[3]


def test_genesys_cloud_ms_to_s_and_acw_excluded(tmp_path):
    snapshot = ROOT / "fixtures" / "vendor_docs_snapshots" / "genesys_cloud" / "analytics.html"
    url = "https://developer.genesys.cloud/analyticsdatamanagement/analytics/detail/aggregations"
    cache = DiskCache(tmp_path / "cache")
    cache.put("http", url, snapshot.read_bytes())

    entry = VendorRegistryEntry(
        slug="genesys_cloud",
        name="Genesys Cloud",
        aliases=[], category="fixed_schema", description="",
        sources=[RegistrySource(kind="html_doc", role="primary", url=url,
                                crawl={"max_depth": 0, "max_pages": 1})],
    )
    llm = LLMClient(cache=cache, offline=True)

    run_pipeline(
        entry=entry, cache=cache, llm=llm,
        catalogs_dir=tmp_path / "catalogs",
        proposed_dir=tmp_path / "proposed",
        reports_dir=tmp_path / "reports",
        report="queue",
    )

    proposed = yaml.safe_load(
        (tmp_path / "proposed" / "genesys_cloud.queue.PROPOSED.yaml").read_text()
    )
    fields = proposed["fields"]

    # Punchline #1: HandleTime composed from talk + hold (NOT tHandle which includes ACW).
    ht = fields["HandleTime"]
    assert "tTalk" in ht and "tHeld" in ht
    assert "tHandle" not in ht
    assert "tAcw" not in ht

    # Punchline #2: ms → s conversion in the formula because canonical unit is duration_seconds.
    assert "/ 1000" in ht
    # And in the leaf duration fields too.
    assert "/ 1000" in fields["HoldTime"]
    assert "/ 1000" in fields["WorkTime"]
    assert "/ 1000" in fields["QueueDelayTime"]

    # Queue key comes across
    assert fields["QueueValue"] == "queueId"
