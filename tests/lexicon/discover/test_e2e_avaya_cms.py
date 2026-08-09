"""E2E regression: Avaya CMS hsplit snapshot → discover pipeline → 10/10 mapping.

Uses a committed HTML snapshot (fixtures/vendor_docs_snapshots/avaya_cms/hsplit.html)
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


def _seed_cache(cache: DiskCache, url: str, path: Path):
    cache.put("http", url, path.read_bytes())


def test_avaya_cms_reproduces_expected_mapping(tmp_path):
    snapshot = ROOT / "fixtures" / "vendor_docs_snapshots" / "avaya_cms" / "hsplit.html"
    assert snapshot.exists(), "Task 24 must create the snapshot before the E2E test"

    url = "https://documentation.avaya.com/en-us/home/bundle/cms/AvayaCMSDBItemsCalculations_r21/DatabaseInfoDatabaseTables/CMSDatabaseTableItems/DatabaseInfoSplitskillDatabaseItems.html"
    cache = DiskCache(tmp_path / "cache")
    _seed_cache(cache, url, snapshot)

    entry = VendorRegistryEntry(
        slug="avaya_cms",
        name="Avaya CMS",
        aliases=[], category="fixed_schema", description="",
        sources=[RegistrySource(kind="html_doc", role="primary", url=url,
                                crawl={"max_depth": 0, "max_pages": 1})],
    )
    llm = LLMClient(cache=cache, offline=True)   # zero LLM cost in CI

    run_pipeline(
        entry=entry, cache=cache, llm=llm,
        catalogs_dir=tmp_path / "catalogs",
        proposed_dir=tmp_path / "proposed",
        reports_dir=tmp_path / "reports",
        report="queue",
    )

    proposed = yaml.safe_load(
        (tmp_path / "proposed" / "avaya_cms.queue.PROPOSED.yaml").read_text()
    )
    fields = proposed["fields"]

    # PUNCHLINES — the wins this project must deliver:
    assert fields["HandleTime"] == "acdtime + holdtime"           # composition, first-time right
    assert fields["WorkTime"] == "acwtime"
    assert fields["HoldTime"] == "holdtime"
    assert fields["QueueDelayTime"] == "anstime"
    assert fields["HandledShort"] == "acceptable"
    assert fields["HandledLong"] == "acdcalls - acceptable"
    assert fields["AbandonedShort"] == "slvlabns"
    assert fields["AbandonedLong"] == "abncalls - slvlabns"
    assert fields["QueueValue"] == "split"
    assert fields["ContactsActive"] == "contactsactive"

    # Confidence rubric: no LLM-only field over 0.85 (this fixture has no LLM path).
    for name, p in proposed["proposals"].items():
        if p.get("proposed") is not None:
            assert p["confidence"] <= 1.0
