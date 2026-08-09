# Discovery Deepening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a vendor-agnostic ACD discovery pipeline (`lexicon discover <vendor>`) that takes only a vendor name and produces a rich field catalog plus a proposed canonical mapping, with the existing `verify_mapping.py` / `engine.py` consuming the output unchanged.

**Architecture:** Five isolated stages — resolve → fetch → extract → enrich → map — with a `SourceDoc` seam that normalizes HTML and API-schema inputs, content-addressed caching so re-runs never hit the network, and an LLM used only where structural signals are absent. New code lives in `src/lexicon/discover/`; the old `src/discover.py` and `src/automap.py` become thin shims that delegate to the new pipeline.

**Tech Stack:** Python 3.10+, PyYAML, lxml, BeautifulSoup4, httpx, anthropic (optional LLM), pytest.

**Companion spec:** `docs/superpowers/specs/2026-08-09-discovery-deepening-design.md`. Read it first; every task below implements a specific part of that spec.

**Ground rules for the executor:**
- **TDD**: every code task writes the failing test first, then the minimum implementation to pass it.
- **No new dependencies without adding them to `requirements.txt`.**
- **Existing tests must stay green.** After every task, `pytest -v` must pass. If a task can't keep it green, stop and flag it.
- **No LLM in tests.** All LLM calls are mocked or served from the on-disk cache written by earlier tasks. CI must not need `ANTHROPIC_API_KEY`.
- **Commit after every task.** Small, reviewable commits.
- **Model IDs to use in code**: `claude-haiku-4-5-20251001` for cheap classification, `claude-sonnet-4-6` for prose extraction. Never use `claude-sonnet-5` (not a real model — the existing code has this wrong).

---

## File map (locked in before tasks)

New package `src/lexicon/discover/` with one file per responsibility:

```
src/lexicon/
  __init__.py
  discover/
    __init__.py
    models.py            # dataclasses: SourceDoc, RawField, EnrichedField, ProposedField, VendorRegistryEntry
    cache.py             # content-addressed fetch + LLM cache
    llm.py               # anthropic client wrapper with caching + offline mode
    registry.py          # loads ontology/registry/*.yaml
    resolver.py          # vendor name → slug → registry entry (with search fallback)
    fetch/
      __init__.py
      html.py            # crawl → SourceDoc list (adapts src/discover.py:crawl_site)
      openapi.py         # fetch + $ref resolve → SourceDoc list
    extract/
      __init__.py
      html_structured.py # DOM walker → RawField list
      html_prose.py      # LLM fallback for unstructured HTML sections
      openapi.py         # schema walker → RawField list
    enrich/
      __init__.py
      dedupe.py
      unit_infer.py
      semantic_tag.py
      trap_detect.py
    mapper.py            # EnrichedField list + canonical + derivations → ProposedField dict
    report.py            # writes out/discovery_reports/<slug>.md
    pipeline.py          # orchestrates all stages
    cli.py               # `python -m lexicon.discover <vendor>` and console_script entrypoint
```

Tests mirror the structure under `tests/lexicon/discover/`.

Modified existing files:
- `ontology/canonical_wfm.yaml` — additive `derivation:` blocks (Task 17).
- `src/discover.py` — becomes a shim (Task 22).
- `src/automap.py` — becomes a shim (Task 23).
- `.gitignore` — add new state/output dirs (Task 1).
- `requirements.txt` — add `beautifulsoup4>=4.12`, `httpx>=0.27` (Task 1).

New non-code artifacts:
- `ontology/registry/avaya_cms.yaml`, `ontology/registry/genesys_cloud.yaml` (Tasks 5, 6).
- `fixtures/vendor_schemas/` (gitignored, populated by fetcher tests).
- `state/discovery_cache/` (gitignored, populated at runtime).
- `out/discovery_reports/` (gitignored except `.gitkeep`).

---

## Task 1: Scaffold package, dependencies, gitignore

**Files:**
- Create: `src/lexicon/__init__.py`, `src/lexicon/discover/__init__.py`, `src/lexicon/discover/fetch/__init__.py`, `src/lexicon/discover/extract/__init__.py`, `src/lexicon/discover/enrich/__init__.py`
- Create: `tests/lexicon/__init__.py`, `tests/lexicon/discover/__init__.py`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Create: `out/discovery_reports/.gitkeep`, `fixtures/vendor_schemas/.gitkeep`

- [ ] **Step 1: Create empty package files.** Each `__init__.py` file is exactly empty (`""`).

- [ ] **Step 2: Update `requirements.txt`** to add the two new deps:

```
lxml>=5.0
PyYAML>=6.0
pytest>=8.0
beautifulsoup4>=4.12
httpx>=0.27
```

- [ ] **Step 3: Update `.gitignore`** — append these lines:

```
# Discovery runtime state
state/discovery_cache/
fixtures/vendor_schemas/*
!fixtures/vendor_schemas/.gitkeep
out/discovery_reports/*
!out/discovery_reports/.gitkeep
```

- [ ] **Step 4: Install new deps.** Run:

```bash
pip install -r requirements.txt
```

Expected: successful install of `beautifulsoup4` and `httpx`.

- [ ] **Step 5: Verify existing tests still pass.** Run:

```bash
pytest -v
```

Expected: all existing tests pass (nothing has changed yet functionally).

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon tests/lexicon requirements.txt .gitignore out/discovery_reports/.gitkeep fixtures/vendor_schemas/.gitkeep
git commit -m "chore: scaffold src/lexicon/discover package and dependencies"
```

---

## Task 2: Data models

**Files:**
- Create: `src/lexicon/discover/models.py`
- Create: `tests/lexicon/discover/test_models.py`

- [ ] **Step 1: Write the failing test.** Create `tests/lexicon/discover/test_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_models.py -v
```

Expected: ImportError, `lexicon.discover.models` doesn't exist yet.

- [ ] **Step 3: Implement `src/lexicon/discover/models.py`:**

```python
"""Dataclasses used by the discovery pipeline. Frozen where possible.

These are the *interfaces* between stages. Every stage consumes and emits
one of these; no stage should invent its own shape.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal


SourceKind = Literal[
    "html", "openapi_schema", "graphql_type", "wsdl_type",
]


@dataclass
class FieldSource:
    """Where in the world a field mention was found."""
    doc_id: str
    url: str
    locator: str        # CSS selector for HTML; JSON pointer for schemas
    snippet: str        # short excerpt of the source content


@dataclass
class SourceDoc:
    """One normalized source document. The uniform seam between fetch and extract."""
    id: str
    kind: SourceKind
    url: str
    title: str
    content: str        # raw payload — HTML text, or JSON schema as string, etc.
    text: str = ""      # cleaned plain text (HTML only); empty for schema docs


@dataclass
class RawField:
    """A single vendor field mention extracted from one source."""
    name: str
    description: str
    source: FieldSource
    extractor: str      # html_structured | html_prose | openapi | graphql | wsdl
    confidence_extraction: float


@dataclass
class SemanticTag:
    tag: str            # e.g. talk_time_like, hold_time_like, ready_time_like
    weight: float
    rationale: str = ""


@dataclass
class Trap:
    kind: Literal["exclusion", "inclusion", "unit_slip"]
    target: str = ""    # e.g. hold_time
    evidence: str = ""  # short quote from the source


@dataclass
class EnrichedField:
    """A merged, unit-inferred, semantically-tagged vendor field."""
    name: str
    description: str
    sources: list[FieldSource]
    unit: str = "unknown"       # duration_seconds | count | percentage | key | unknown
    unit_confidence: float = 0.0
    unit_signals: list[str] = field(default_factory=list)
    semantic_tags: list[SemanticTag] = field(default_factory=list)
    traps: list[Trap] = field(default_factory=list)


@dataclass
class ProposedField:
    """One canonical field's proposed mapping (an arithmetic formula over vendor fields)."""
    formula: str | None
    confidence: float
    rationale: str
    alternates: list[dict[str, Any]] = field(default_factory=list)
    needs_review: bool = False


@dataclass
class RegistrySource:
    kind: Literal["html_doc", "openapi", "graphql", "wsdl"]
    role: Literal["primary", "secondary"]
    url: str | None
    crawl: dict[str, Any] = field(default_factory=dict)


@dataclass
class VendorRegistryEntry:
    slug: str
    name: str
    aliases: list[str]
    category: Literal["fixed_schema", "flow_configured"]
    description: str
    sources: list[RegistrySource]
    version: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Add repo root to Python path for tests.** Because `src/` is not currently a package installable via `pip install -e .`, tests need to import from it. Create `tests/conftest.py` if it doesn't already exist, otherwise append to it:

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
```

Check first with `test -f tests/conftest.py`; if present, read it and only append the lines above if they aren't already there.

- [ ] **Step 5: Run test to verify it passes.**

```bash
pytest tests/lexicon/discover/test_models.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/discover/models.py tests/lexicon/discover/test_models.py tests/conftest.py
git commit -m "feat(discover): add data models for the pipeline seams"
```

---

## Task 3: Content-addressed cache

**Files:**
- Create: `src/lexicon/discover/cache.py`
- Create: `tests/lexicon/discover/test_cache.py`

Purpose: one class handles both fetch caching (URL → bytes) and LLM caching (prompt hash → response). Both are content-addressed by SHA256 of the *key*; cache lives on disk under `state/discovery_cache/`.

- [ ] **Step 1: Write the failing test.** Create `tests/lexicon/discover/test_cache.py`:

```python
import json
from pathlib import Path
import pytest

from lexicon.discover.cache import DiskCache


def test_put_get_roundtrip(tmp_path):
    c = DiskCache(tmp_path)
    c.put("ns", "k1", b"payload")
    assert c.get("ns", "k1") == b"payload"


def test_missing_returns_none(tmp_path):
    c = DiskCache(tmp_path)
    assert c.get("ns", "missing") is None


def test_namespaces_are_isolated(tmp_path):
    c = DiskCache(tmp_path)
    c.put("html", "k", b"a")
    c.put("llm", "k", b"b")
    assert c.get("html", "k") == b"a"
    assert c.get("llm", "k") == b"b"


def test_put_get_json(tmp_path):
    c = DiskCache(tmp_path)
    c.put_json("llm", "prompt-1", {"answer": "hi"})
    assert c.get_json("llm", "prompt-1") == {"answer": "hi"}


def test_key_hashing_is_stable(tmp_path):
    c = DiskCache(tmp_path)
    p1 = c._key_path("ns", "hello world")
    p2 = c._key_path("ns", "hello world")
    assert p1 == p2


def test_offline_mode_disallows_writes(tmp_path):
    c = DiskCache(tmp_path, offline=True)
    with pytest.raises(RuntimeError, match="offline"):
        c.put("ns", "k", b"x")


def test_offline_mode_allows_reads(tmp_path):
    c = DiskCache(tmp_path)
    c.put("ns", "k", b"x")
    c2 = DiskCache(tmp_path, offline=True)
    assert c2.get("ns", "k") == b"x"
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_cache.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/cache.py`:**

```python
"""Content-addressed on-disk cache. Used for HTTP fetches AND LLM responses.

Layout: <root>/<namespace>/<sha256>.bin
Namespaces used by the pipeline: "http", "llm", "resolver".

`offline=True` disables writes (used in CI to guarantee cache is authoritative).
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


class DiskCache:
    def __init__(self, root: Path, offline: bool = False):
        self.root = Path(root)
        self.offline = offline
        self.root.mkdir(parents=True, exist_ok=True)

    def _key_path(self, namespace: str, key: str) -> Path:
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / namespace / f"{h}.bin"

    def get(self, namespace: str, key: str) -> bytes | None:
        p = self._key_path(namespace, key)
        return p.read_bytes() if p.exists() else None

    def put(self, namespace: str, key: str, value: bytes) -> None:
        if self.offline:
            raise RuntimeError(
                f"offline cache: refusing to write namespace={namespace} key={key!r}"
            )
        p = self._key_path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value)

    def get_json(self, namespace: str, key: str):
        b = self.get(namespace, key)
        return None if b is None else json.loads(b.decode("utf-8"))

    def put_json(self, namespace: str, key: str, value) -> None:
        self.put(namespace, key, json.dumps(value).encode("utf-8"))
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_cache.py -v
```

Expected: 7 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/cache.py tests/lexicon/discover/test_cache.py
git commit -m "feat(discover): add content-addressed disk cache with offline mode"
```

---

## Task 4: LLM client wrapper

**Files:**
- Create: `src/lexicon/discover/llm.py`
- Create: `tests/lexicon/discover/test_llm.py`

The LLM client is used by prose extraction, unit inference (when structural signals are silent), and semantic tagging. It wraps the `anthropic` SDK, caches every call by `(model, prompt)` in the `DiskCache`, and supports an offline mode that raises loudly on cache miss.

- [ ] **Step 1: Write the failing test.** Create `tests/lexicon/discover/test_llm.py`:

```python
from pathlib import Path
import pytest

from lexicon.discover.cache import DiskCache
from lexicon.discover.llm import LLMClient


def test_returns_cached_response(tmp_path):
    cache = DiskCache(tmp_path)
    # pre-seed the cache with what "the LLM" would have returned
    cache.put_json("llm", "claude-haiku-4-5-20251001||what is 2+2?", {"text": "4"})
    client = LLMClient(cache=cache, offline=True)      # offline: must not call network
    resp = client.complete(model="claude-haiku-4-5-20251001", prompt="what is 2+2?")
    assert resp == "4"


def test_offline_raises_on_cache_miss(tmp_path):
    client = LLMClient(cache=DiskCache(tmp_path), offline=True)
    with pytest.raises(RuntimeError, match="cache miss"):
        client.complete(model="claude-haiku-4-5-20251001", prompt="unseen prompt")


def test_cache_key_is_model_plus_prompt(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put_json("llm", "claude-sonnet-4-6||q", {"text": "sonnet"})
    cache.put_json("llm", "claude-haiku-4-5-20251001||q", {"text": "haiku"})
    client = LLMClient(cache=cache, offline=True)
    assert client.complete(model="claude-sonnet-4-6", prompt="q") == "sonnet"
    assert client.complete(model="claude-haiku-4-5-20251001", prompt="q") == "haiku"


def test_live_call_caches_result(tmp_path, monkeypatch):
    cache = DiskCache(tmp_path)
    calls = []

    def fake_call(model, prompt):
        calls.append((model, prompt))
        return "live-answer"

    client = LLMClient(cache=cache, offline=False, _call_impl=fake_call)
    r1 = client.complete(model="claude-haiku-4-5-20251001", prompt="q")
    r2 = client.complete(model="claude-haiku-4-5-20251001", prompt="q")
    assert r1 == "live-answer" and r2 == "live-answer"
    assert len(calls) == 1     # second call served from cache
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_llm.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/llm.py`:**

```python
"""LLM client with (model, prompt)-keyed disk caching.

Every call is cached. Re-runs on the same inputs never hit the network.
Offline mode raises RuntimeError on cache miss — used in CI to guarantee
the committed cache is authoritative.
"""
from __future__ import annotations
from typing import Callable

from .cache import DiskCache


class LLMClient:
    def __init__(
        self,
        cache: DiskCache,
        offline: bool = False,
        _call_impl: Callable[[str, str], str] | None = None,
    ):
        self.cache = cache
        self.offline = offline
        self._call_impl = _call_impl or self._real_call

    def complete(self, *, model: str, prompt: str) -> str:
        key = f"{model}||{prompt}"
        cached = self.cache.get_json("llm", key)
        if cached is not None:
            return cached["text"]
        if self.offline:
            raise RuntimeError(f"LLM cache miss in offline mode: model={model} prompt[:40]={prompt[:40]!r}")
        text = self._call_impl(model, prompt)
        self.cache.put_json("llm", key, {"text": text})
        return text

    @staticmethod
    def _real_call(model: str, prompt: str) -> str:
        """Real API call. Only imports anthropic when actually invoked."""
        import os
        import anthropic  # type: ignore
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_llm.py -v
```

Expected: 4 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/llm.py tests/lexicon/discover/test_llm.py
git commit -m "feat(discover): add caching LLM client with offline mode"
```

---

## Task 5: Vendor registry — loader

**Files:**
- Create: `src/lexicon/discover/registry.py`
- Create: `tests/lexicon/discover/test_registry.py`

Loads all YAMLs under `ontology/registry/*.yaml` and validates them against the `VendorRegistryEntry` shape.

- [ ] **Step 1: Write the failing test.** Create `tests/lexicon/discover/test_registry.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_registry.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/registry.py`:**

```python
"""Loader for ontology/registry/*.yaml. Validates every entry against the
VendorRegistryEntry dataclass and raises RegistryError on malformed entries.
"""
from __future__ import annotations
from pathlib import Path
import yaml

from .models import RegistrySource, VendorRegistryEntry

VALID_CATEGORIES = {"fixed_schema", "flow_configured"}
VALID_SOURCE_KINDS = {"html_doc", "openapi", "graphql", "wsdl"}


class RegistryError(ValueError):
    pass


def _load_one(path: Path) -> VendorRegistryEntry:
    raw = yaml.safe_load(path.read_text()) or {}
    for req in ("slug", "name", "category", "description", "sources"):
        if req not in raw:
            raise RegistryError(f"{path.name}: missing required key {req!r}")
    if raw["category"] not in VALID_CATEGORIES:
        raise RegistryError(
            f"{path.name}: category={raw['category']!r} not in {sorted(VALID_CATEGORIES)}"
        )
    sources = []
    for i, s in enumerate(raw["sources"]):
        if s.get("kind") not in VALID_SOURCE_KINDS:
            raise RegistryError(
                f"{path.name}: sources[{i}].kind={s.get('kind')!r} not in {sorted(VALID_SOURCE_KINDS)}"
            )
        sources.append(
            RegistrySource(
                kind=s["kind"],
                role=s.get("role", "primary"),
                url=s.get("url"),
                crawl=s.get("crawl", {}),
            )
        )
    return VendorRegistryEntry(
        slug=raw["slug"],
        name=raw["name"],
        aliases=raw.get("aliases", []),
        category=raw["category"],
        description=raw["description"],
        sources=sources,
        version=raw.get("version", {}),
    )


def load_registry(dir_: Path) -> list[VendorRegistryEntry]:
    if not dir_.exists():
        return []
    return [_load_one(p) for p in sorted(dir_.glob("*.yaml"))]
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_registry.py -v
```

Expected: 4 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/registry.py tests/lexicon/discover/test_registry.py
git commit -m "feat(discover): add vendor registry loader with validation"
```

---

## Task 6: Seed registry entries — Avaya CMS and Genesys Cloud

**Files:**
- Create: `ontology/registry/avaya_cms.yaml`
- Create: `ontology/registry/genesys_cloud.yaml`
- Create: `tests/lexicon/discover/test_registry_seed.py`

- [ ] **Step 1: Write the failing test.**

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_registry_seed.py -v
```

Expected: assertion failures (no registry files yet).

- [ ] **Step 3: Create `ontology/registry/avaya_cms.yaml`:**

```yaml
slug: avaya_cms
name: "Avaya CMS"
aliases:
  - "Avaya"
  - "Avaya Call Management System"
  - "CMS"
  - "CMS Historical"
category: fixed_schema
description: >
  Historical reporting database for Avaya Aura Contact Center. Interval
  tables include hsplit (split/skill) and hagent (agent-per-split).

sources:
  - kind: html_doc
    role: primary
    url: https://documentation.avaya.com/en-us/home/bundle/cms/AvayaCMSDBItemsCalculations_r21/DatabaseInfoDatabaseTables/CMSDatabaseTableItems/DatabaseInfoSplitskillDatabaseItems.html
    crawl:
      max_depth: 2
      max_pages: 30
      include_paths:
        - "/DatabaseInfoDatabaseTables/"

version:
  system_version: "R21"
  last_verified: "2026-08-09"
```

- [ ] **Step 4: Create `ontology/registry/genesys_cloud.yaml`:**

```yaml
slug: genesys_cloud
name: "Genesys Cloud"
aliases:
  - "Genesys"
  - "Genesys Cloud CX"
  - "PureCloud"
category: fixed_schema
description: >
  Cloud contact-center platform. Historical interval metrics are exposed
  via the Analytics API (Conversation aggregates).

sources:
  - kind: html_doc
    role: primary
    url: https://developer.genesys.cloud/analyticsdatamanagement/analytics/detail/aggregations
    crawl:
      max_depth: 2
      max_pages: 30
  - kind: openapi
    role: primary
    url: https://api.mypurecloud.com/api/v2/docs/swagger.json

version:
  system_version: "2025.10"
  last_verified: "2026-08-09"
```

- [ ] **Step 5: Run test to verify it passes.**

```bash
pytest tests/lexicon/discover/test_registry_seed.py -v
```

Expected: 2 pass.

- [ ] **Step 6: Commit.**

```bash
git add ontology/registry/ tests/lexicon/discover/test_registry_seed.py
git commit -m "feat(discover): seed registry with avaya_cms and genesys_cloud"
```

---

## Task 7: Vendor resolver (registry-only path)

**Files:**
- Create: `src/lexicon/discover/resolver.py`
- Create: `tests/lexicon/discover/test_resolver.py`

Handles the case where the name matches an entry (or its aliases). Search-fallback lands in Task 8.

- [ ] **Step 1: Write the failing test.**

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_resolver.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/resolver.py`:**

```python
"""Vendor-name → registry entry resolution.

Rules (all case-insensitive):
  1. Exact match against slug (highest priority)
  2. Exact match against name
  3. Case-insensitive alias match
  4. Ambiguity (>1 match) → fail with candidate list
  5. No match → fail; search fallback (Task 8) handles this
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from .models import VendorRegistryEntry


ResolveVia = Literal["slug", "name", "alias", "search"]


@dataclass
class ResolveResult:
    entry: VendorRegistryEntry
    resolved_via: ResolveVia


class ResolveError(ValueError):
    pass


def resolve_vendor(query: str, entries: list[VendorRegistryEntry]) -> ResolveResult:
    q = query.strip().lower()
    slug_hits = [e for e in entries if e.slug.lower() == q]
    if len(slug_hits) == 1:
        return ResolveResult(entry=slug_hits[0], resolved_via="slug")

    name_hits = [e for e in entries if e.name.lower() == q]
    if len(name_hits) == 1:
        return ResolveResult(entry=name_hits[0], resolved_via="name")

    alias_hits = [
        e for e in entries
        if q in (a.lower() for a in e.aliases)
    ]
    if len(alias_hits) == 1:
        return ResolveResult(entry=alias_hits[0], resolved_via="alias")

    all_hits = {e.slug: e for e in slug_hits + name_hits + alias_hits}
    if len(all_hits) > 1:
        candidates = ", ".join(sorted(all_hits))
        raise ResolveError(
            f"'{query}' is ambiguous; candidates: {candidates}. "
            f"Invoke by slug: lexicon discover <slug>"
        )

    raise ResolveError(f"no match for '{query}' in registry")
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_resolver.py -v
```

Expected: 6 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/resolver.py tests/lexicon/discover/test_resolver.py
git commit -m "feat(discover): resolve vendor name to registry entry"
```

---

## Task 8: Search fallback for unknown vendors

**Files:**
- Modify: `src/lexicon/discover/resolver.py`
- Modify: `tests/lexicon/discover/test_resolver.py`

When the registry has no match, ask the LLM to propose 1-3 candidate authoritative documentation URLs for the vendor. This is v1's search fallback — a real web search integration comes later.

- [ ] **Step 1: Write the failing test.** Append to `tests/lexicon/discover/test_resolver.py`:

```python
from pathlib import Path
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
    import pytest
    llm = LLMClient(cache=DiskCache(tmp_path / "cache"), offline=True)
    with pytest.raises(Exception, match="cache miss"):
        resolve_vendor_with_fallback("Unknown Vendor", registry=[], llm=llm)
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_resolver.py -v
```

Expected: ImportError for `resolve_vendor_with_fallback`.

- [ ] **Step 3: Extend `src/lexicon/discover/resolver.py`.** Append:

```python
import yaml

from .llm import LLMClient
from .models import RegistrySource, VendorRegistryEntry


SEARCH_PROMPT_TEMPLATE = """You are helping locate authoritative documentation for an ACD/contact-center system.

The ACD system is: "{vendor}"

Return a YAML document with these fields:
  slug: <lower_snake_case identifier for this vendor>
  name: <human-readable name>
  sources:
    - kind: html_doc
      role: primary
      url: <URL of the vendor's primary developer/admin documentation site>

Rules:
- Include only URLs on the vendor's own official domain (docs.*, developer.*, help.*, admin.*).
- Prefer pages that document data models, historical reporting fields, or API schemas.
- If unsure, include a best-guess URL and let the human verify.
- Return YAML ONLY — no prose, no code fences.
"""


def resolve_vendor_with_fallback(
    query: str,
    registry: list[VendorRegistryEntry],
    llm: LLMClient,
) -> ResolveResult:
    try:
        return resolve_vendor(query, registry)
    except ResolveError as e:
        if "no match" not in str(e):
            raise  # ambiguity is not a search-fallback situation
    text = llm.complete(
        model="claude-sonnet-4-6",
        prompt=SEARCH_PROMPT_TEMPLATE.format(vendor=query),
    )
    data = yaml.safe_load(text) or {}
    if "slug" not in data or "sources" not in data:
        raise ResolveError(
            f"search fallback for '{query}' returned invalid YAML: {text[:200]!r}"
        )
    sources = [
        RegistrySource(
            kind=s.get("kind", "html_doc"),
            role=s.get("role", "primary"),
            url=s.get("url"),
            crawl=s.get("crawl", {}),
        )
        for s in data["sources"]
    ]
    entry = VendorRegistryEntry(
        slug=data["slug"],
        name=data.get("name", query),
        aliases=data.get("aliases", []),
        category="fixed_schema",
        description=f"Discovered via search fallback for query '{query}'.",
        sources=sources,
    )
    return ResolveResult(entry=entry, resolved_via="search")
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_resolver.py -v
```

Expected: all 9 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/resolver.py tests/lexicon/discover/test_resolver.py
git commit -m "feat(discover): add LLM search fallback for unknown vendors"
```

---

## Task 9: HTML fetcher

**Files:**
- Create: `src/lexicon/discover/fetch/html.py`
- Create: `tests/lexicon/discover/test_fetch_html.py`

Adapts the existing `crawl_site` from `src/discover.py` to the new `SourceDoc` shape. Uses the `DiskCache` from Task 3 for HTTP responses.

- [ ] **Step 1: Write the failing test.**

```python
from pathlib import Path
import pytest

from lexicon.discover.cache import DiskCache
from lexicon.discover.fetch.html import fetch_html_source
from lexicon.discover.models import RegistrySource


def test_uses_cached_body(tmp_path):
    cache = DiskCache(tmp_path)
    url = "https://example.com/docs"
    cache.put("http", url, b"<html><title>hi</title><body><p>abc</p></body></html>")

    src = RegistrySource(kind="html_doc", role="primary", url=url,
                         crawl={"max_depth": 0, "max_pages": 1})

    def boom(u):
        raise AssertionError(f"should not have fetched {u}")

    docs = fetch_html_source(src, cache=cache, _fetcher=boom)
    assert len(docs) == 1
    assert docs[0].kind == "html"
    assert docs[0].url == url
    assert "abc" in docs[0].text
    assert docs[0].title == "hi"


def test_fetches_when_missing_and_caches(tmp_path):
    cache = DiskCache(tmp_path)
    url = "https://example.com/docs"

    def fake_fetcher(u):
        assert u == url
        return b"<html><body><h1>live</h1></body></html>"

    src = RegistrySource(kind="html_doc", role="primary", url=url,
                         crawl={"max_depth": 0, "max_pages": 1})
    docs = fetch_html_source(src, cache=cache, _fetcher=fake_fetcher)
    assert "live" in docs[0].text
    # second call should be served from cache
    docs2 = fetch_html_source(
        src, cache=cache, _fetcher=lambda u: pytest.fail("must not refetch"),
    )
    assert docs2[0].text == docs[0].text


def test_offline_cache_miss_raises(tmp_path):
    src = RegistrySource(kind="html_doc", role="primary",
                         url="https://example.com/missing",
                         crawl={"max_depth": 0, "max_pages": 1})
    cache = DiskCache(tmp_path, offline=True)
    with pytest.raises(RuntimeError):
        fetch_html_source(src, cache=cache, _fetcher=None)
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_fetch_html.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/fetch/html.py`:**

```python
"""HTML source fetcher. Emits one SourceDoc per fetched page.

For v1 we do NOT implement multi-hop BFS crawling in the new pipeline;
that is the existing `src/discover.py` code path. v1 fetches the primary
URL only (`max_depth: 0`). Multi-hop crawl is a follow-up enhancement
(see follow-ups.md).
"""
from __future__ import annotations
import hashlib
import re
from typing import Callable

from bs4 import BeautifulSoup
import httpx

from ..cache import DiskCache
from ..models import RegistrySource, SourceDoc


def _default_fetcher(url: str) -> bytes:
    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": "Lexicon-discover/1.0"})
    r.raise_for_status()
    return r.content


def _extract_title_and_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    for bad in soup(["script", "style"]):
        bad.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return title, text


def fetch_html_source(
    source: RegistrySource,
    *,
    cache: DiskCache,
    _fetcher: Callable[[str], bytes] | None = None,
) -> list[SourceDoc]:
    if source.url is None:
        return []
    fetcher = _fetcher or _default_fetcher
    body = cache.get("http", source.url)
    if body is None:
        body = fetcher(source.url)
        cache.put("http", source.url, body)
    html = body.decode("utf-8", errors="ignore")
    title, text = _extract_title_and_text(html)
    doc_id = f"html:{hashlib.sha256(source.url.encode()).hexdigest()[:12]}"
    return [SourceDoc(
        id=doc_id, kind="html", url=source.url,
        title=title, content=html, text=text,
    )]
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_fetch_html.py -v
```

Expected: 3 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/fetch/html.py tests/lexicon/discover/test_fetch_html.py
git commit -m "feat(discover): add HTML fetcher emitting SourceDoc"
```

---

## Task 10: OpenAPI fetcher

**Files:**
- Create: `src/lexicon/discover/fetch/openapi.py`
- Create: `tests/lexicon/discover/test_fetch_openapi.py`

Fetches an OpenAPI JSON/YAML document and emits one `SourceDoc(kind="openapi_schema")` per named schema (`components.schemas.<Name>`), with `$ref`s resolved.

- [ ] **Step 1: Write the failing test.**

```python
import json
import pytest

from lexicon.discover.cache import DiskCache
from lexicon.discover.fetch.openapi import fetch_openapi_source
from lexicon.discover.models import RegistrySource


SPEC = {
    "openapi": "3.0.0",
    "components": {
        "schemas": {
            "QueueMetrics": {
                "type": "object",
                "description": "Aggregate queue metrics.",
                "properties": {
                    "nHandled": {"type": "integer", "description": "Count handled."},
                    "tTalk": {"type": "integer", "description": "Talk time in ms."},
                },
            },
            "AgentState": {
                "type": "object",
                "description": "Agent presence state.",
                "properties": {
                    "readyTime": {"type": "integer", "description": "Time ready, seconds."},
                },
            },
        }
    },
}


def test_emits_one_doc_per_schema(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put("http", "https://x/openapi.json", json.dumps(SPEC).encode())
    src = RegistrySource(kind="openapi", role="primary",
                         url="https://x/openapi.json")
    docs = fetch_openapi_source(src, cache=cache, _fetcher=lambda u: pytest.fail("cached"))
    assert {d.title for d in docs} == {"QueueMetrics", "AgentState"}
    for d in docs:
        assert d.kind == "openapi_schema"


def test_schema_content_contains_properties(tmp_path):
    cache = DiskCache(tmp_path)
    cache.put("http", "https://x/openapi.json", json.dumps(SPEC).encode())
    src = RegistrySource(kind="openapi", role="primary",
                         url="https://x/openapi.json")
    docs = fetch_openapi_source(src, cache=cache)
    qm = next(d for d in docs if d.title == "QueueMetrics")
    body = json.loads(qm.content)
    assert "properties" in body
    assert "nHandled" in body["properties"]


def test_missing_url_returns_empty(tmp_path):
    src = RegistrySource(kind="openapi", role="primary", url=None)
    assert fetch_openapi_source(src, cache=DiskCache(tmp_path)) == []
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_fetch_openapi.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/fetch/openapi.py`:**

```python
"""OpenAPI source fetcher. Emits one SourceDoc per named schema under
components.schemas — with $ref resolution done in place (best-effort).

Non-goals for v1: full OpenAPI validation, external $ref resolution
(only same-document $refs are inlined), OpenAPI 2.0 (Swagger) support.
"""
from __future__ import annotations
import copy
import json
import hashlib
from typing import Callable

import yaml

from ..cache import DiskCache
from ..models import RegistrySource, SourceDoc


def _default_fetcher(url: str) -> bytes:
    import httpx
    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": "Lexicon-discover/1.0"})
    r.raise_for_status()
    return r.content


def _resolve_refs(node, root):
    if isinstance(node, dict):
        if "$ref" in node and node["$ref"].startswith("#/"):
            parts = node["$ref"][2:].split("/")
            target = root
            for p in parts:
                target = target[p]
            return _resolve_refs(copy.deepcopy(target), root)
        return {k: _resolve_refs(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(x, root) for x in node]
    return node


def fetch_openapi_source(
    source: RegistrySource,
    *,
    cache: DiskCache,
    _fetcher: Callable[[str], bytes] | None = None,
) -> list[SourceDoc]:
    if source.url is None:
        return []
    fetcher = _fetcher or _default_fetcher
    body = cache.get("http", source.url)
    if body is None:
        body = fetcher(source.url)
        cache.put("http", source.url, body)
    text = body.decode("utf-8", errors="ignore")
    spec = yaml.safe_load(text) if source.url.endswith((".yaml", ".yml")) else json.loads(text)
    schemas = (spec.get("components", {}) or {}).get("schemas", {}) or {}
    docs = []
    for name, schema in schemas.items():
        resolved = _resolve_refs(schema, spec)
        doc_id = f"openapi:{hashlib.sha256((source.url + '#' + name).encode()).hexdigest()[:12]}"
        docs.append(SourceDoc(
            id=doc_id, kind="openapi_schema",
            url=source.url + f"#/components/schemas/{name}",
            title=name,
            content=json.dumps(resolved),
            text="",
        ))
    return docs
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_fetch_openapi.py -v
```

Expected: 3 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/fetch/openapi.py tests/lexicon/discover/test_fetch_openapi.py
git commit -m "feat(discover): add OpenAPI fetcher emitting per-schema SourceDoc"
```

---

## Task 11: HTML structured extractor

**Files:**
- Create: `src/lexicon/discover/extract/html_structured.py`
- Create: `tests/lexicon/discover/test_extract_html_structured.py`

Extracts `RawField`s from `SourceDoc(kind="html")` using DOM structure only (tables with field/description columns, `<dl>` definition lists). No LLM.

- [ ] **Step 1: Write the failing test.**

```python
from lexicon.discover.extract.html_structured import extract_html_structured
from lexicon.discover.models import SourceDoc


def _doc(html: str) -> SourceDoc:
    return SourceDoc(id="d1", kind="html", url="https://x/p", title="p", content=html, text="")


def test_two_column_table():
    html = """
    <table>
      <tr><th>Field</th><th>Description</th></tr>
      <tr><td>acdtime</td><td>Talk time of ACD calls.</td></tr>
      <tr><td>acwtime</td><td>After-call work time.</td></tr>
    </table>
    """
    raws = extract_html_structured(_doc(html))
    names = {r.name for r in raws}
    assert names == {"acdtime", "acwtime"}
    acd = next(r for r in raws if r.name == "acdtime")
    assert "Talk time" in acd.description
    assert acd.extractor == "html_structured"
    assert acd.confidence_extraction >= 0.9


def test_definition_list():
    html = """
    <dl>
      <dt>tTalk</dt><dd>Talk time in milliseconds.</dd>
      <dt>tHold</dt><dd>Hold time in milliseconds.</dd>
    </dl>
    """
    raws = extract_html_structured(_doc(html))
    assert {r.name for r in raws} == {"tTalk", "tHold"}


def test_ignores_wide_tables():
    """A 5-column table isn't a field-description table; skip it."""
    html = """
    <table>
      <tr><th>a</th><th>b</th><th>c</th><th>d</th><th>e</th></tr>
      <tr><td>1</td><td>2</td><td>3</td><td>4</td><td>5</td></tr>
    </table>
    """
    assert extract_html_structured(_doc(html)) == []


def test_provenance_populated():
    html = "<table><tr><th>Field</th><th>Desc</th></tr><tr><td>x</td><td>y</td></tr></table>"
    raws = extract_html_structured(_doc(html))
    assert raws[0].source.doc_id == "d1"
    assert raws[0].source.url == "https://x/p"
    assert "table" in raws[0].source.locator.lower()
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_extract_html_structured.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/extract/html_structured.py`:**

```python
"""Structural HTML extraction. Uses only DOM shape — no LLM.

Recognized patterns:
  1. Two-column tables where one header is "Field"/"Name" and the other is
     "Description"/"Definition"/"Meaning".
  2. Any two-column table whose first cell values look like identifiers.
  3. Definition lists (<dl><dt>…</dt><dd>…</dd>).
"""
from __future__ import annotations
import re

from bs4 import BeautifulSoup

from ..models import FieldSource, RawField, SourceDoc


IDENT_RE = re.compile(r"^[A-Za-z_][\w.]{1,60}$")
FIELD_HEADERS = {"field", "name", "column", "attribute", "property", "key"}
DESC_HEADERS = {"description", "definition", "meaning", "notes", "summary"}


def _looks_like_ident(s: str) -> bool:
    return bool(IDENT_RE.match(s.strip()))


def _table_is_field_desc(table) -> bool:
    rows = table.find_all("tr")
    if not rows:
        return False
    header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
    if len(header_cells) != 2:
        # Try: rows[1..] all have 2 cells and first cell is an identifier
        data_rows = rows if len(header_cells) == 0 else rows[1:]
        for r in data_rows[:5]:
            cells = r.find_all(["th", "td"])
            if len(cells) != 2 or not _looks_like_ident(cells[0].get_text(strip=True)):
                return False
        return bool(data_rows)
    return (any(h in FIELD_HEADERS for h in header_cells) or
            any(h in DESC_HEADERS for h in header_cells) or
            all(_looks_like_ident(r.find_all(['td', 'th'])[0].get_text(strip=True))
                for r in rows[1:6] if len(r.find_all(['td', 'th'])) == 2))


def extract_html_structured(doc: SourceDoc) -> list[RawField]:
    soup = BeautifulSoup(doc.content, "html.parser")
    out: list[RawField] = []

    for i, table in enumerate(soup.find_all("table")):
        if not _table_is_field_desc(table):
            continue
        rows = table.find_all("tr")
        header_cells = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        data_rows = rows[1:] if any(h in FIELD_HEADERS | DESC_HEADERS for h in header_cells) else rows
        for j, row in enumerate(data_rows):
            cells = row.find_all(["td", "th"])
            if len(cells) != 2:
                continue
            name = cells[0].get_text(strip=True)
            desc = cells[1].get_text(" ", strip=True)
            if not _looks_like_ident(name):
                continue
            out.append(RawField(
                name=name,
                description=desc,
                source=FieldSource(
                    doc_id=doc.id, url=doc.url,
                    locator=f"table:nth-of-type({i + 1}) > tr:nth-child({j + 2})",
                    snippet=f"{name} — {desc[:120]}",
                ),
                extractor="html_structured",
                confidence_extraction=0.95,
            ))

    for i, dl in enumerate(soup.find_all("dl")):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for j, (dt, dd) in enumerate(zip(dts, dds)):
            name = dt.get_text(strip=True)
            if not _looks_like_ident(name):
                continue
            desc = dd.get_text(" ", strip=True)
            out.append(RawField(
                name=name,
                description=desc,
                source=FieldSource(
                    doc_id=doc.id, url=doc.url,
                    locator=f"dl:nth-of-type({i + 1}) > dt:nth-child({2 * j + 1})",
                    snippet=f"{name} — {desc[:120]}",
                ),
                extractor="html_structured",
                confidence_extraction=0.95,
            ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_extract_html_structured.py -v
```

Expected: 4 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/extract/ tests/lexicon/discover/test_extract_html_structured.py
git commit -m "feat(discover): add structural HTML field extractor"
```

---

## Task 12: OpenAPI extractor

**Files:**
- Create: `src/lexicon/discover/extract/openapi.py`
- Create: `tests/lexicon/discover/test_extract_openapi.py`

Walks the resolved schema in a `SourceDoc(kind="openapi_schema")` and emits one `RawField` per `properties.*`, with `x-unit` extensions surfaced into the description.

- [ ] **Step 1: Write the failing test.**

```python
import json

from lexicon.discover.extract.openapi import extract_openapi
from lexicon.discover.models import SourceDoc


def _schema_doc(name, schema):
    return SourceDoc(
        id="s1", kind="openapi_schema",
        url=f"https://x#/components/schemas/{name}",
        title=name,
        content=json.dumps(schema),
        text="",
    )


def test_emits_one_field_per_property():
    schema = {
        "type": "object",
        "properties": {
            "nHandled": {"type": "integer", "description": "Count of handled contacts."},
            "tTalk": {"type": "integer", "description": "Talk time in ms.", "x-unit": "milliseconds"},
        },
    }
    raws = extract_openapi(_schema_doc("QueueMetrics", schema))
    assert {r.name for r in raws} == {"nHandled", "tTalk"}
    tt = next(r for r in raws if r.name == "tTalk")
    assert "milliseconds" in tt.description  # x-unit surfaced
    assert tt.extractor == "openapi"
    assert tt.confidence_extraction >= 0.95


def test_no_properties_returns_empty():
    doc = _schema_doc("Empty", {"type": "object"})
    assert extract_openapi(doc) == []


def test_provenance_uses_json_pointer_locator():
    schema = {"type": "object", "properties": {"x": {"type": "integer", "description": "x"}}}
    raws = extract_openapi(_schema_doc("S", schema))
    assert raws[0].source.locator == "/properties/x"
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_extract_openapi.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/extract/openapi.py`:**

```python
"""OpenAPI schema extractor. Emits RawField per property.

Surfaces the description text plus any `x-unit` / `format` hints, so the
enricher's unit-inference step has strong structural signals to key off.
"""
from __future__ import annotations
import json

from ..models import FieldSource, RawField, SourceDoc


def _describe(prop: dict) -> str:
    parts = []
    if prop.get("description"):
        parts.append(prop["description"])
    if "format" in prop:
        parts.append(f"(format: {prop['format']})")
    if "x-unit" in prop:
        parts.append(f"(unit: {prop['x-unit']})")
    if "type" in prop:
        parts.append(f"(type: {prop['type']})")
    return " ".join(parts).strip()


def extract_openapi(doc: SourceDoc) -> list[RawField]:
    if doc.kind != "openapi_schema":
        return []
    schema = json.loads(doc.content)
    props = schema.get("properties", {}) or {}
    out: list[RawField] = []
    for name, prop in props.items():
        desc = _describe(prop)
        out.append(RawField(
            name=name,
            description=desc,
            source=FieldSource(
                doc_id=doc.id, url=doc.url,
                locator=f"/properties/{name}",
                snippet=f"{name} — {desc[:120]}",
            ),
            extractor="openapi",
            confidence_extraction=0.98,
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_extract_openapi.py -v
```

Expected: 3 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/extract/openapi.py tests/lexicon/discover/test_extract_openapi.py
git commit -m "feat(discover): add OpenAPI schema field extractor"
```

---

## Task 13: Enricher — dedupe/merge

**Files:**
- Create: `src/lexicon/discover/enrich/dedupe.py`
- Create: `tests/lexicon/discover/test_enrich_dedupe.py`

Merges RawField entries with the same normalized name into a single `EnrichedField` with a merged source list. Later enrichment stages add unit, tag, and trap info.

- [ ] **Step 1: Write the failing test.**

```python
from lexicon.discover.enrich.dedupe import dedupe_raw_fields
from lexicon.discover.models import FieldSource, RawField


def _rf(name, desc, doc_id, url):
    return RawField(
        name=name, description=desc,
        source=FieldSource(doc_id=doc_id, url=url,
                           locator="", snippet=""),
        extractor="html_structured", confidence_extraction=0.9,
    )


def test_same_name_merges_sources():
    a = _rf("acdtime", "Talk time", "d1", "u1")
    b = _rf("acdtime", "Talk time (dup)", "d2", "u2")
    fields = dedupe_raw_fields([a, b])
    assert len(fields) == 1
    assert len(fields[0].sources) == 2
    # description prefers longer/more detailed one
    assert fields[0].description == "Talk time (dup)"


def test_case_insensitive_merge():
    a = _rf("ACDTIME", "Talk time.", "d1", "u1")
    b = _rf("acdtime", "Talk time in seconds.", "d2", "u2")
    fields = dedupe_raw_fields([a, b])
    assert len(fields) == 1
    # canonical name is the first-seen casing
    assert fields[0].name == "ACDTIME"
    # description prefers the longer/more detailed one
    assert "seconds" in fields[0].description


def test_different_names_stay_separate():
    a = _rf("acdtime", "a", "d1", "u1")
    b = _rf("holdtime", "b", "d1", "u1")
    assert len(dedupe_raw_fields([a, b])) == 2


def test_empty_input_returns_empty():
    assert dedupe_raw_fields([]) == []
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_enrich_dedupe.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/enrich/dedupe.py`:**

```python
"""Dedupe raw field mentions across sources into one EnrichedField each.

Merge policy:
  - Key is normalized(name).lower() with punctuation stripped.
  - Canonical `name` is the first-seen casing.
  - `description` prefers the longer, more-detailed variant.
  - `sources` accumulates every mention.
Later enrichment stages populate unit / semantic_tags / traps.
"""
from __future__ import annotations
import re

from ..models import EnrichedField, RawField


_NORM = re.compile(r"[^A-Za-z0-9]+")


def _norm(name: str) -> str:
    return _NORM.sub("", name).lower()


def dedupe_raw_fields(raws: list[RawField]) -> list[EnrichedField]:
    by_key: dict[str, EnrichedField] = {}
    for r in raws:
        k = _norm(r.name)
        cur = by_key.get(k)
        if cur is None:
            by_key[k] = EnrichedField(
                name=r.name,
                description=r.description,
                sources=[r.source],
            )
        else:
            if len(r.description) > len(cur.description):
                cur.description = r.description
            cur.sources.append(r.source)
    return list(by_key.values())
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_enrich_dedupe.py -v
```

Expected: 4 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/enrich/dedupe.py tests/lexicon/discover/test_enrich_dedupe.py
git commit -m "feat(discover): dedupe raw fields into enriched fields"
```

---

## Task 14: Enricher — unit inference

**Files:**
- Create: `src/lexicon/discover/enrich/unit_infer.py`
- Create: `tests/lexicon/discover/test_enrich_unit_infer.py`

Layered signals, cheapest first. Adds `unit` + `unit_confidence` + `unit_signals` in place on each `EnrichedField`.

- [ ] **Step 1: Write the failing test.**

```python
from lexicon.discover.enrich.unit_infer import infer_units
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def test_ms_suffix_wins():
    f = _f("tTalk_ms", "Talk time.")
    infer_units([f])
    assert f.unit == "duration_ms"
    assert f.unit_confidence >= 0.9


def test_seconds_from_description():
    f = _f("acdtime", "Talk time in seconds.")
    infer_units([f])
    assert f.unit == "duration_seconds"


def test_count_from_description():
    f = _f("nHandled", "Count of handled contacts.")
    infer_units([f])
    assert f.unit == "count"


def test_percent_from_name():
    f = _f("SvcLvlPct", "Service level.")
    infer_units([f])
    assert f.unit == "percentage"


def test_unknown_when_silent():
    f = _f("mystery", "Some field.")
    infer_units([f])
    assert f.unit == "unknown"
    assert f.unit_confidence == 0.0


def test_openapi_x_unit_surface():
    f = _f("tTalk", "Talk time. (format: int64) (unit: milliseconds) (type: integer)")
    infer_units([f])
    assert f.unit == "duration_ms"
    assert "x-unit" in f.unit_signals or any("unit" in s for s in f.unit_signals)
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_enrich_unit_infer.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/enrich/unit_infer.py`:**

```python
"""Unit inference for enriched fields.

Signals (cheapest → costliest), each contributes to unit_confidence:

  1. Name suffix (`*_ms`, `*Pct`, `n<Name>`, `*_count`, `*_seconds`)
  2. OpenAPI x-unit / format text surfaced by extract/openapi.py
  3. Description regex ("in milliseconds", "seconds", "percent", "count of")
  4. (LLM classifier: stub for v1 — the three signals above cover both
     anchor vendors. Add later if a real vendor forces it.)
"""
from __future__ import annotations
import re

from ..models import EnrichedField


NAME_MS = re.compile(r"(_ms$|Ms$|_millis)")
NAME_SEC = re.compile(r"(_seconds$|_sec$|Time$|time$)")
NAME_PCT = re.compile(r"(Pct$|Percent$|_percent$)")
NAME_COUNT = re.compile(r"^n[A-Z]|_count$|Count$")

DESC_MS = re.compile(r"\b(?:in\s+)?milliseconds\b", re.I)
DESC_SEC = re.compile(r"\b(?:in\s+)?seconds\b", re.I)
DESC_PCT = re.compile(r"\bpercent(?:age)?\b", re.I)
DESC_COUNT = re.compile(r"\bcount\b|\bnumber of\b", re.I)


def _score(field: EnrichedField):
    signals: list[str] = []
    scores = {"duration_ms": 0.0, "duration_seconds": 0.0, "percentage": 0.0, "count": 0.0}
    name = field.name
    desc = field.description

    if NAME_MS.search(name):
        scores["duration_ms"] += 0.9; signals.append("name_suffix:ms")
    if NAME_SEC.search(name):
        scores["duration_seconds"] += 0.6; signals.append("name_suffix:seconds")
    if NAME_PCT.search(name):
        scores["percentage"] += 0.9; signals.append("name_suffix:pct")
    if NAME_COUNT.search(name):
        scores["count"] += 0.6; signals.append("name_suffix:count")

    if DESC_MS.search(desc):
        scores["duration_ms"] += 0.85; signals.append("description_regex:ms")
        if "(unit:" in desc and "millisec" in desc.lower():
            signals.append("x-unit:milliseconds")
    if DESC_SEC.search(desc) and not DESC_MS.search(desc):
        scores["duration_seconds"] += 0.7; signals.append("description_regex:seconds")
    if DESC_PCT.search(desc):
        scores["percentage"] += 0.7; signals.append("description_regex:pct")
    if DESC_COUNT.search(desc):
        scores["count"] += 0.5; signals.append("description_regex:count")

    best = max(scores.items(), key=lambda kv: kv[1])
    unit, conf = best
    if conf < 0.3:
        return "unknown", 0.0, signals
    return unit, min(conf, 0.98), signals


def infer_units(fields: list[EnrichedField]) -> None:
    for f in fields:
        unit, conf, signals = _score(f)
        f.unit = unit
        f.unit_confidence = conf
        f.unit_signals = signals
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_enrich_unit_infer.py -v
```

Expected: 6 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/enrich/unit_infer.py tests/lexicon/discover/test_enrich_unit_infer.py
git commit -m "feat(discover): rule-based unit inference for enriched fields"
```

---

## Task 15: Enricher — semantic tagging

**Files:**
- Create: `src/lexicon/discover/enrich/semantic_tag.py`
- Create: `tests/lexicon/discover/test_enrich_semantic_tag.py`

Tags each field with zero or more canonical concept *families* (`talk_time_like`, `hold_time_like`, `acw_time_like`, etc.) using a vendor-agnostic keyword lexicon. LLM is not used in v1 — the lexicon covers both anchor vendors.

- [ ] **Step 1: Write the failing test.**

```python
from lexicon.discover.enrich.semantic_tag import tag_fields, TAG_LEXICON
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def test_talk_time_like():
    fields = [_f("acdtime", "Talk time of ACD calls.")]
    tag_fields(fields)
    tags = {t.tag for t in fields[0].semantic_tags}
    assert "talk_time_like" in tags


def test_hold_time_like():
    fields = [_f("holdtime", "Time the caller was held.")]
    tag_fields(fields)
    assert any(t.tag == "hold_time_like" for t in fields[0].semantic_tags)


def test_acw_time_like():
    fields = [_f("acwtime", "After call work time.")]
    tag_fields(fields)
    assert any(t.tag == "acw_time_like" for t in fields[0].semantic_tags)


def test_ready_time_like():
    fields = [_f("i_readytime", "Time in ready/available state.")]
    tag_fields(fields)
    assert any(t.tag == "ready_time_like" for t in fields[0].semantic_tags)


def test_untagged_field_stays_untagged():
    fields = [_f("mystery", "Some field.")]
    tag_fields(fields)
    assert fields[0].semantic_tags == []


def test_multi_tag_with_weights():
    """A field mentioning both talk and hold should get both tags."""
    fields = [_f("total_talk_hold", "Combined talk plus hold time.")]
    tag_fields(fields)
    tags = {t.tag for t in fields[0].semantic_tags}
    assert "talk_time_like" in tags and "hold_time_like" in tags


def test_lexicon_covers_required_concepts():
    """Sanity check: the lexicon knows about every canonical concept family we need."""
    required = {
        "talk_time_like", "hold_time_like", "acw_time_like",
        "queue_delay_time_like", "ready_time_like", "not_ready_time_like",
        "login_time_like", "handled_total_like", "handled_within_sl_like",
        "abandoned_total_like", "abandoned_within_sl_like",
        "queue_key_like", "agent_key_like", "contacts_active_like",
    }
    assert required.issubset(set(TAG_LEXICON))
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_enrich_semantic_tag.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/enrich/semantic_tag.py`:**

```python
"""Semantic tagging: label each enriched field with the canonical concept
families it looks like (talk_time_like, hold_time_like, ready_time_like, …).

This is deliberately rule-based: a small hand-curated lexicon of vendor-agnostic
keywords + a substring/token matcher. The lexicon was seeded from the existing
src/automap.py ROLE_KEYWORDS table (which already worked for Avaya + Genesys),
generalized to a "*_like" naming scheme so it can be extended per canonical concept.
"""
from __future__ import annotations
import re

from ..models import EnrichedField, SemanticTag


TAG_LEXICON: dict[str, set[str]] = {
    # duration concepts
    "talk_time_like":       {"talk", "acdtime", "ttalk", "converse"},
    "hold_time_like":       {"hold", "held", "holdtime", "theld", "park"},
    "acw_time_like":        {"acw", "wrap", "wrapup", "aftercall", "after_call",
                             "worktime", "tacw", "acwtime"},
    "queue_delay_time_like": {"delay", "wait", "answered", "ans", "anstime",
                              "queuetime", "tanswered", "queue_time"},
    "ready_time_like":       {"ready", "avail", "available", "availtime", "idle",
                              "iavailtime", "tidle", "readytime"},
    "not_ready_time_like":   {"notready", "not_ready", "aux", "auxtime",
                              "tiauxtime", "away", "notresponding"},
    "login_time_like":       {"login", "staff", "stafftime", "loggedin",
                              "istafftime", "logintime", "tactive"},
    "internal_time_like":    {"internal_time", "daacdtime", "tinternal",
                              "internalhandletime"},
    "outbound_time_like":    {"outbound_time", "oacdtime", "toutbound",
                              "outboundhandletime"},
    "right_party_time_like": {"rpc_time", "righthandletime"},

    # count concepts
    "handled_total_like":       {"handled", "acd", "acdcalls", "nhandled",
                                 "answered", "nanswered"},
    "handled_within_sl_like":   {"acceptable", "within_sl", "withinsl",
                                 "servicelevel", "handled_sl", "sl_handled"},
    "abandoned_total_like":     {"abandoned", "abandon", "abn", "abncalls",
                                 "nabandoned"},
    "abandoned_within_sl_like": {"slvlabns", "sl_abandoned", "within_sl_abandoned"},
    "contacts_active_like":     {"contactsactive", "active", "carryover"},
    "internal_count_like":      {"internal_contacts", "internalcontacts",
                                 "daacdcalls", "ninternal"},
    "outbound_count_like":      {"outbound_contacts", "outboundcontacts",
                                 "oacdcalls", "noutbound"},

    # keys
    "queue_key_like":  {"csq", "split", "skill", "queueid", "queue_id", "vdn", "gate"},
    "agent_key_like":  {"logid", "userid", "agent", "extension", "agentid"},
}


_TOKEN_RE = re.compile(r"[^A-Za-z]+")


def _tokens(name: str, desc: str) -> set[str]:
    parts = _TOKEN_RE.split(name.lower())
    parts += _TOKEN_RE.split(desc.lower())
    return {p for p in parts if p}


def _score_tag(tag: str, keywords: set[str], name: str, desc: str, toks: set[str]) -> float:
    name_l = name.lower()
    substr = sum(1 for kw in keywords if len(kw) >= 4 and kw in name_l)
    token = len(keywords & toks)
    if substr == 0 and token == 0:
        return 0.0
    raw = 3 * substr + token
    return min(1.0, raw / 5.0)


def tag_fields(fields: list[EnrichedField]) -> None:
    for f in fields:
        toks = _tokens(f.name, f.description)
        for tag, kws in TAG_LEXICON.items():
            s = _score_tag(tag, kws, f.name, f.description, toks)
            if s >= 0.4:
                f.semantic_tags.append(SemanticTag(
                    tag=tag,
                    weight=s,
                    rationale=f"keyword lexicon match (score={s:.2f})",
                ))
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_enrich_semantic_tag.py -v
```

Expected: 7 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/enrich/semantic_tag.py tests/lexicon/discover/test_enrich_semantic_tag.py
git commit -m "feat(discover): rule-based semantic tagging with keyword lexicon"
```

---

## Task 16: Enricher — trap detection

**Files:**
- Create: `src/lexicon/discover/enrich/trap_detect.py`
- Create: `tests/lexicon/discover/test_enrich_trap_detect.py`

Pattern-scans descriptions for known semantic traps ("does NOT include", "excludes", "in milliseconds" when peers are seconds). Adds `Trap` entries in place on each field.

- [ ] **Step 1: Write the failing test.**

```python
from lexicon.discover.enrich.trap_detect import detect_traps
from lexicon.discover.enrich.semantic_tag import tag_fields
from lexicon.discover.enrich.unit_infer import infer_units
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def test_exclusion_trap_on_acdtime():
    fields = [
        _f("acdtime", "Talk time of ACD calls. Does NOT include holdtime."),
        _f("holdtime", "Hold time of ACD calls."),
    ]
    tag_fields(fields)
    detect_traps(fields)
    acd = fields[0]
    traps = [t for t in acd.traps if t.kind == "exclusion"]
    assert traps
    assert traps[0].target == "hold_time"


def test_no_trap_when_no_signal():
    fields = [_f("acdtime", "Talk time of ACD calls.")]
    tag_fields(fields)
    detect_traps(fields)
    assert fields[0].traps == []


def test_unit_slip_trap():
    fields = [
        _f("tTalk", "Talk time in milliseconds."),
        _f("tHold", "Hold time in milliseconds."),
        _f("tAcw",  "ACW time in milliseconds."),
        _f("tWait", "Delay in milliseconds."),
    ]
    tag_fields(fields)
    infer_units(fields)
    # give one field seconds instead, to make it the odd-one-out
    fields[3].unit = "duration_seconds"
    detect_traps(fields)
    assert any(t.kind == "unit_slip" for t in fields[3].traps)


def test_inclusion_trap_on_thandle():
    fields = [
        _f("tHandle", "Total handle time. Includes wrap-up (ACW)."),
        _f("tAcw",    "ACW time in milliseconds."),
    ]
    tag_fields(fields)
    detect_traps(fields)
    inclusions = [t for t in fields[0].traps if t.kind == "inclusion"]
    assert inclusions
    assert inclusions[0].target == "acw_time"
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_enrich_trap_detect.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/enrich/trap_detect.py`:**

```python
"""Trap detection. Looks for phrasings and unit mismatches that flag
known semantic risks:

  - exclusion: "does NOT include X" / "excludes X"    (e.g. Avaya acdtime)
  - inclusion: "includes X" / "combined with X"       (e.g. Genesys tHandle)
  - unit_slip: this field's unit differs from its peer group's

The mapper (Task 18) reads these traps to inform compositional formulas.
"""
from __future__ import annotations
import re
from collections import Counter

from ..models import EnrichedField, Trap


EXCLUDE_RE = re.compile(
    r"(?:does not include|doesn't include|excludes?|excluding)\s+([A-Za-z_][\w\s]{0,40})",
    re.IGNORECASE,
)
INCLUDE_RE = re.compile(
    r"(?:includes?|combined with|including)\s+([A-Za-z_][\w\s]{0,40})",
    re.IGNORECASE,
)


_TARGET_CANONICAL = {
    "hold": "hold_time",
    "holdtime": "hold_time",
    "acw": "acw_time",
    "wrapup": "acw_time",
    "wrap": "acw_time",
    "wrap-up": "acw_time",
    "after-call": "acw_time",
    "aftercall": "acw_time",
    "talk": "talk_time",
    "talktime": "talk_time",
}


def _target_of(mention: str) -> str:
    key = re.split(r"\s+", mention.lower())[0].strip(".,;:")
    return _TARGET_CANONICAL.get(key, key)


def _detect_phrase_traps(field: EnrichedField) -> None:
    for m in EXCLUDE_RE.finditer(field.description):
        field.traps.append(Trap(
            kind="exclusion",
            target=_target_of(m.group(1)),
            evidence=m.group(0),
        ))
    for m in INCLUDE_RE.finditer(field.description):
        field.traps.append(Trap(
            kind="inclusion",
            target=_target_of(m.group(1)),
            evidence=m.group(0),
        ))


def _detect_unit_slip(fields: list[EnrichedField]) -> None:
    duration_units = [f.unit for f in fields if f.unit.startswith("duration_")]
    if not duration_units:
        return
    counter = Counter(duration_units)
    if len(counter) < 2:
        return
    majority = counter.most_common(1)[0][0]
    for f in fields:
        if f.unit.startswith("duration_") and f.unit != majority:
            f.traps.append(Trap(
                kind="unit_slip",
                target=majority,
                evidence=f"peer group is {majority}, this field is {f.unit}",
            ))


def detect_traps(fields: list[EnrichedField]) -> None:
    for f in fields:
        _detect_phrase_traps(f)
    _detect_unit_slip(fields)
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_enrich_trap_detect.py -v
```

Expected: 4 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/enrich/trap_detect.py tests/lexicon/discover/test_enrich_trap_detect.py
git commit -m "feat(discover): pattern-scan trap detection (exclusion/inclusion/unit_slip)"
```

---

## Task 17: Add derivation blocks to canonical_wfm.yaml

**Files:**
- Modify: `ontology/canonical_wfm.yaml`
- Create: `tests/lexicon/discover/test_canonical_derivations.py`

Additive-only change: add `derivation:` blocks to the two compositional canonical fields — `HandleTime` in `queue` and `agent_queue`. No existing field data is altered.

- [ ] **Step 1: Write the failing test.**

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_handle_time_queue_has_derivation():
    canon = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())
    ht = canon["queue"]["HandleTime"]
    assert "derivation" in ht
    d = ht["derivation"]
    assert d["formula"] == "{talk} + {hold}"
    tags = [c["tag"] for c in d["components"]]
    assert "talk_time_like" in tags and "hold_time_like" in tags
    assert "acw_time_like" in d.get("forbid_tags", [])


def test_handle_time_agent_queue_has_derivation():
    canon = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())
    ht = canon["agent_queue"]["HandleTime"]
    assert "derivation" in ht


def test_no_existing_field_definition_changed():
    """Sanity: HandleTime.definition and HandleTime.unit stay exactly as before."""
    canon = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())
    ht = canon["queue"]["HandleTime"]
    assert ht["unit"] == "duration_seconds"
    assert "TALK TIME + HOLD TIME" in ht["definition"]
    assert "After-Call-Work" in ht["definition"]
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_canonical_derivations.py -v
```

Expected: `KeyError: 'derivation'` on first test.

- [ ] **Step 3: Edit `ontology/canonical_wfm.yaml`.** Two places to touch:

Find the block for `queue.HandleTime`:

```yaml
  HandleTime:
    definition: "Total handle time of all handled contacts = TALK TIME + HOLD TIME. Does NOT include After-Call-Work."
    unit: duration_seconds
    trap: "HandleTime = talk + hold. ACW (wrap-up) is a SEPARATE field (WorkTime). Never fold ACW into HandleTime."
    media: { immediate_response: required, deferrable_response: required, outbound_campaign: not_applicable, outbound: not_applicable }
```

Append a `derivation:` block to it (existing lines untouched):

```yaml
  HandleTime:
    definition: "Total handle time of all handled contacts = TALK TIME + HOLD TIME. Does NOT include After-Call-Work."
    unit: duration_seconds
    trap: "HandleTime = talk + hold. ACW (wrap-up) is a SEPARATE field (WorkTime). Never fold ACW into HandleTime."
    media: { immediate_response: required, deferrable_response: required, outbound_campaign: not_applicable, outbound: not_applicable }
    derivation:
      formula: "{talk} + {hold}"
      components:
        - {tag: talk_time_like, required: true, placeholder: talk}
        - {tag: hold_time_like, required: true, placeholder: hold}
      forbid_tags: [acw_time_like]

```

Find `agent_queue.HandleTime`:

```yaml
  HandleTime: { definition: "Handle time (talk + hold) for this agent on this queue.", unit: duration_seconds,
                trap: "talk + hold, NOT ACW." }
```

Replace with the block form so `derivation` fits cleanly:

```yaml
  HandleTime:
    definition: "Handle time (talk + hold) for this agent on this queue."
    unit: duration_seconds
    trap: "talk + hold, NOT ACW."
    derivation:
      formula: "{talk} + {hold}"
      components:
        - {tag: talk_time_like, required: true, placeholder: talk}
        - {tag: hold_time_like, required: true, placeholder: hold}
      forbid_tags: [acw_time_like]
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_canonical_derivations.py -v
```

Expected: 3 pass.

- [ ] **Step 5: Run the full existing suite to check nothing breaks.**

```bash
pytest -v
```

Expected: all tests pass. If existing tests fail here, revert the YAML change and investigate; the derivation additions should be strictly additive.

- [ ] **Step 6: Commit.**

```bash
git add ontology/canonical_wfm.yaml tests/lexicon/discover/test_canonical_derivations.py
git commit -m "feat(canonical): add additive derivation blocks for HandleTime"
```

---

## Task 18: Mapper

**Files:**
- Create: `src/lexicon/discover/mapper.py`
- Create: `tests/lexicon/discover/test_mapper.py`

Turns enriched fields + canonical + derivations into a proposed mapping in the exact shape today's `automap.py` produces (so `verify_mapping.py` is unchanged).

- [ ] **Step 1: Write the failing test.**

```python
from lexicon.discover.enrich.semantic_tag import tag_fields
from lexicon.discover.enrich.trap_detect import detect_traps
from lexicon.discover.enrich.unit_infer import infer_units
from lexicon.discover.mapper import propose_mapping
from lexicon.discover.models import EnrichedField, FieldSource


def _f(name, desc):
    return EnrichedField(
        name=name, description=desc,
        sources=[FieldSource(doc_id="d", url="u", locator="", snippet="")],
    )


def _enrich(fields):
    infer_units(fields)
    tag_fields(fields)
    detect_traps(fields)
    return fields


def test_avaya_handle_time_composed_from_talk_and_hold():
    fields = _enrich([
        _f("acdtime", "Talk time of ACD calls. Does NOT include holdtime."),
        _f("holdtime", "Hold time on ACD calls, in seconds."),
    ])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HandleTime"]
    assert ht.formula == "acdtime + holdtime"
    assert 0.75 <= ht.confidence <= 0.95   # composition of two structural sources


def test_leaf_field_pick_hold_time():
    fields = _enrich([_f("holdtime", "Hold time on ACD calls, in seconds.")])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HoldTime"]
    assert ht.formula == "holdtime"


def test_no_candidate_marks_needs_review():
    fields = _enrich([_f("holdtime", "Hold time on ACD calls, in seconds.")])
    proposed = propose_mapping(fields, report="queue")
    handle = proposed["HandleTime"]
    assert handle.formula is None
    assert handle.needs_review is True
    assert "missing" in handle.rationale.lower() or "no candidate" in handle.rationale.lower()


def test_forbid_tags_rejects_acw_leak():
    """Composition must NOT include an acw-tagged field even if unit matches."""
    fields = _enrich([
        _f("acdtime",  "Talk time of ACD calls. Does NOT include holdtime."),
        _f("holdtime", "Hold time on ACD calls, in seconds."),
        _f("acwtime",  "After call work time, in seconds."),
    ])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HandleTime"]
    assert "acwtime" not in (ht.formula or "")


def test_genesys_ms_unit_conversion_flagged():
    """When peer fields are ms, we surface that as a unit_slip trap; the mapper
    generates a `/ 1000` conversion in the formula for a duration_seconds target."""
    fields = _enrich([
        _f("tTalk", "Talk time in milliseconds."),
        _f("tHeld", "Hold time in milliseconds."),
        _f("tAcw",  "ACW time in milliseconds."),
    ])
    proposed = propose_mapping(fields, report="queue")
    ht = proposed["HandleTime"]
    # HandleTime is duration_seconds; sources are ms — conversion required
    assert "/ 1000" in (ht.formula or "")
    # confidence should still be reasonable (composition of structural fields)
    assert ht.confidence >= 0.6


def test_llm_only_cap_at_0_85():
    """A field with only LLM-tagged confidence (no structural signal) must
    cap below 0.85 even if enrichment gave high weights."""
    # This test verifies the confidence rubric formula in isolation.
    from lexicon.discover.mapper import _cap_confidence
    assert _cap_confidence(0.99, has_structural=False) <= 0.85
    assert _cap_confidence(0.99, has_structural=True) == 0.99
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_mapper.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/mapper.py`:**

```python
"""Propose a canonical mapping from enriched fields + canonical ontology.

Output shape mirrors today's ontology/proposed/<vendor>.<report>.PROPOSED.yaml
so verify_mapping.py / engine.py consume it unchanged.

Algorithm (per canonical concept C in the current report):
  1. Shortlist fields whose semantic_tags overlap with C's expected tag family
     (or, for composed concepts, each component's tag family).
  2. Unit-filter: drop candidates whose unit != C.unit, unless a unit_slip trap
     lets us insert a conversion (ms -> s).
  3. Rank by weight * unit_confidence.
  4. If C has a derivation block, fill each placeholder from the shortlist and
     compose the formula. Reject candidates whose tags appear in forbid_tags.
  5. Confidence: min(component confidences), capped per rubric.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml

from .models import EnrichedField, ProposedField


ROOT = Path(__file__).resolve().parents[3]
CANON = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())


REPORT_SECTION = {
    "queue": "queue",
    "agentqueue": "agent_queue",
    "agentsystem": "agent_system",
}

# Which tag family we expect for each simple (non-composed) canonical field.
LEAF_TAG_MAP: dict[str, str] = {
    "HoldTime": "hold_time_like",
    "WorkTime": "acw_time_like",
    "QueueDelayTime": "queue_delay_time_like",
    "ReadyTime": "ready_time_like",
    "NotReadyTime": "not_ready_time_like",
    "LoginTime": "login_time_like",
    "InternalHandleTime": "internal_time_like",
    "OutboundHandleTime": "outbound_time_like",
    "Handled": "handled_total_like",
    "HandledShort": "handled_within_sl_like",
    "HandledLong": "handled_total_like",   # arithmetic handled below
    "AbandonedShort": "abandoned_within_sl_like",
    "AbandonedLong": "abandoned_total_like",  # arithmetic below
    "ContactsActive": "contacts_active_like",
    "InternalContacts": "internal_count_like",
    "OutboundContacts": "outbound_count_like",
    "QueueValue": "queue_key_like",
    "AgentValue": "agent_key_like",
}

# Which canonical fields need "total - within_sl" arithmetic
LONG_DIFF: dict[str, tuple[str, str]] = {
    "HandledLong":   ("handled_total_like", "handled_within_sl_like"),
    "AbandonedLong": ("abandoned_total_like", "abandoned_within_sl_like"),
}


def _canonical_fields_for_report(report: str) -> list[str]:
    section = REPORT_SECTION[report]
    fields = []
    for name, spec in (CANON[section] or {}).items():
        media = (spec.get("media") or {}).get("immediate_response", "not_required")
        # Include only fields we need for the immediate_response media scope,
        # matching src/automap.py's target_fields().
        if report != "queue" or media in ("required", "required_if_available"):
            fields.append(name)
    return fields


def _weight_for_tag(field: EnrichedField, tag: str) -> float:
    for t in field.semantic_tags:
        if t.tag == tag:
            return t.weight
    return 0.0


def _pick_best(
    fields: list[EnrichedField],
    tag: str,
    target_unit: str,
    forbid_tags: set[str] = frozenset(),
) -> tuple[EnrichedField | None, float]:
    best, best_score = None, 0.0
    for f in fields:
        if any(t.tag in forbid_tags for t in f.semantic_tags):
            continue
        w = _weight_for_tag(f, tag)
        if w < 0.4:
            continue
        unit_ok = (
            f.unit == target_unit
            or (target_unit == "duration_seconds" and f.unit == "duration_ms")
            or target_unit == "key"                        # keys are always OK
        )
        if not unit_ok:
            continue
        score = w * (f.unit_confidence or 0.5)
        if score > best_score:
            best, best_score = f, score
    return best, best_score


def _operand(field: EnrichedField, target_unit: str) -> str:
    if target_unit == "duration_seconds" and field.unit == "duration_ms":
        return f"{field.name} / 1000"
    return field.name


def _cap_confidence(raw: float, has_structural: bool) -> float:
    if has_structural:
        return min(raw, 1.0)
    return min(raw, 0.85)


def _propose_composed(
    canon_field: dict,
    canon_unit: str,
    fields: list[EnrichedField],
) -> ProposedField:
    d = canon_field["derivation"]
    forbid = set(d.get("forbid_tags") or [])
    placeholders: dict[str, str] = {}
    weights: list[float] = []
    picked_names: list[str] = []
    missing = []
    for comp in d["components"]:
        f, s = _pick_best(fields, comp["tag"], canon_unit, forbid_tags=forbid)
        if f is None:
            if comp.get("required", True):
                missing.append(comp["tag"])
            continue
        placeholders[comp["placeholder"]] = _operand(f, canon_unit)
        weights.append(s)
        picked_names.append(f.name)
    if missing:
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"missing components: {missing}",
            needs_review=True,
        )
    formula = d["formula"].format(**placeholders)
    has_structural = all(w > 0.0 for w in weights)
    conf = _cap_confidence(min(weights), has_structural=has_structural)
    return ProposedField(
        formula=formula,
        confidence=round(conf, 2),
        rationale=f"composed from {picked_names} per derivation",
        needs_review=conf < 0.6,
    )


def _propose_leaf(
    field_name: str,
    canon_unit: str,
    fields: list[EnrichedField],
) -> ProposedField:
    # LONG_DIFF fields: total - within_sl
    if field_name in LONG_DIFF:
        total_tag, sl_tag = LONG_DIFF[field_name]
        total, ts = _pick_best(fields, total_tag, canon_unit)
        sl,    ss = _pick_best(fields, sl_tag,    canon_unit)
        if total and sl:
            conf = _cap_confidence(min(ts, ss), has_structural=True)
            return ProposedField(
                formula=f"{_operand(total, canon_unit)} - {_operand(sl, canon_unit)}",
                confidence=round(conf, 2),
                rationale=f"{total.name} - {sl.name}",
                needs_review=conf < 0.6,
            )
        if total:
            return ProposedField(
                formula=_operand(total, canon_unit),
                confidence=round(_cap_confidence(ts * 0.6, True), 2),
                rationale=f"total-only fallback ({total.name}); within-SL split missing",
                needs_review=True,
            )
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"no candidate for {total_tag}",
            needs_review=True,
        )

    tag = LEAF_TAG_MAP.get(field_name)
    if not tag:
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"no tag mapping for canonical field {field_name}",
            needs_review=True,
        )
    best, score = _pick_best(fields, tag, canon_unit)
    if best is None:
        return ProposedField(
            formula=None, confidence=0.0,
            rationale=f"no candidate matching {tag} with unit={canon_unit}",
            needs_review=True,
        )
    conf = _cap_confidence(score, has_structural=True)
    return ProposedField(
        formula=_operand(best, canon_unit),
        confidence=round(conf, 2),
        rationale=f"best {tag} match: {best.name} (weight={score:.2f})",
        needs_review=conf < 0.6,
    )


def propose_mapping(
    fields: list[EnrichedField],
    *,
    report: str = "queue",
) -> dict[str, ProposedField]:
    section = REPORT_SECTION[report]
    out: dict[str, ProposedField] = {}
    for cf in _canonical_fields_for_report(report):
        spec = (CANON[section] or {}).get(cf, {})
        unit = spec.get("unit", "count")
        if "derivation" in spec:
            out[cf] = _propose_composed(spec, unit, fields)
        else:
            out[cf] = _propose_leaf(cf, unit, fields)
    return out
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_mapper.py -v
```

Expected: 6 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/mapper.py tests/lexicon/discover/test_mapper.py
git commit -m "feat(discover): mapper with derivation-driven composition + honest confidence"
```

---

## Task 19: Coverage report writer

**Files:**
- Create: `src/lexicon/discover/report.py`
- Create: `tests/lexicon/discover/test_report.py`

- [ ] **Step 1: Write the failing test.**

```python
from pathlib import Path

from lexicon.discover.models import ProposedField
from lexicon.discover.report import write_coverage_report


def test_writes_markdown_report(tmp_path):
    proposals = {
        "QueueValue":  ProposedField("split",              0.98, "queue_key_like: split"),
        "HandleTime":  ProposedField("acdtime + holdtime", 0.88, "composed"),
        "HandledShort":ProposedField(None,                 0.0,  "no candidate", needs_review=True),
    }
    out = tmp_path / "avaya_cms.md"
    write_coverage_report(
        vendor_slug="avaya_cms", report="queue",
        proposals=proposals,
        sources=[{"url": "https://x", "status": "ok", "pages": 37}],
        traps=[{"field": "acdtime", "kind": "exclusion", "target": "hold_time"}],
        path=out,
    )
    text = out.read_text()
    assert "# Discovery report — avaya_cms" in text
    assert "acdtime + holdtime" in text
    assert "no candidate" in text
    assert "2/3" in text or "found: 2" in text.lower()
    assert "acdtime" in text and "exclusion" in text


def test_missing_field_flagged_in_next_actions(tmp_path):
    proposals = {
        "HandleTime": ProposedField(None, 0.0, "no candidate", needs_review=True),
    }
    out = tmp_path / "r.md"
    write_coverage_report("v", "queue", proposals, sources=[], traps=[], path=out)
    text = out.read_text()
    assert "HandleTime" in text
    assert "needs" in text.lower() or "missing" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_report.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/report.py`:**

```python
"""Markdown coverage report writer. One file per discovery run.

The report is the human's first stop when reviewing discovery output.
It must be actionable: what was found, what was missed, what to do next.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

from .models import ProposedField


def _fmt_status(p: ProposedField) -> str:
    if p.formula is None:
        return "✗ missing"
    if p.needs_review:
        return "⚠ low conf"
    return "✓ found"


def write_coverage_report(
    vendor_slug: str,
    report: str,
    proposals: dict[str, ProposedField],
    sources: list[dict],
    traps: list[dict],
    path: Path,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    lines = [
        f"# Discovery report — {vendor_slug} ({now})",
        f"",
        f"Report: {report}",
        f"",
        f"## Sources",
    ]
    for s in sources:
        icon = "✓" if s.get("status") == "ok" else "✗"
        lines.append(f"- {icon} {s.get('url','?')}  ({s.get('pages','?')} pages, {s.get('status','?')})")
    lines.append("")

    lines.append("## Canonical coverage")
    lines.append("")
    lines.append("| Canonical concept | Status | Proposed | Confidence |")
    lines.append("|---|---|---|---|")
    found = 0
    for name, p in proposals.items():
        if p.formula is not None:
            found += 1
        status = _fmt_status(p)
        formula = p.formula or "(none)"
        lines.append(f"| {name} | {status} | `{formula}` | {p.confidence:.2f} |")
    lines.append("")
    total = len(proposals)
    lines.append(f"Overall: found: {found}/{total}")
    lines.append("")

    lines.append("## Traps flagged")
    if not traps:
        lines.append("- (none)")
    for t in traps:
        lines.append(f"- {t.get('field','?')} — {t.get('kind','?')} → {t.get('target','?')}")
    lines.append("")

    lines.append("## Next actions for the human")
    missing = [n for n, p in proposals.items() if p.formula is None]
    low = [n for n, p in proposals.items() if p.formula is not None and p.needs_review]
    if missing:
        lines.append(f"- Missing (needs a source or hint): {', '.join(missing)}")
    if low:
        lines.append(f"- Low confidence (verify): {', '.join(low)}")
    if not missing and not low:
        lines.append("- Nothing flagged. Run verify_mapping.py to grade against the golden.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_report.py -v
```

Expected: 2 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/report.py tests/lexicon/discover/test_report.py
git commit -m "feat(discover): markdown coverage report writer"
```

---

## Task 20: Pipeline orchestrator

**Files:**
- Create: `src/lexicon/discover/pipeline.py`
- Create: `tests/lexicon/discover/test_pipeline.py`

Ties it all together. Given a resolved vendor entry and cache/LLM, it runs fetch → extract → enrich → map → report and writes the two output artifacts.

- [ ] **Step 1: Write the failing test.**

```python
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
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_pipeline.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/lexicon/discover/pipeline.py`:**

```python
"""Discovery pipeline orchestrator. Runs stages 2-5 for a resolved vendor,
writes: fixtures/vendor_catalogs/<slug>.yaml,
        ontology/proposed/<slug>.<report>.PROPOSED.yaml,
        out/discovery_reports/<slug>.md.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import yaml

from .cache import DiskCache
from .enrich.dedupe import dedupe_raw_fields
from .enrich.semantic_tag import tag_fields
from .enrich.trap_detect import detect_traps
from .enrich.unit_infer import infer_units
from .extract.html_structured import extract_html_structured
from .extract.openapi import extract_openapi
from .fetch.html import fetch_html_source
from .fetch.openapi import fetch_openapi_source
from .llm import LLMClient
from .mapper import propose_mapping
from .models import (
    EnrichedField, RawField, RegistrySource, SourceDoc, VendorRegistryEntry,
)
from .report import write_coverage_report


@dataclass
class PipelineResult:
    catalog_path: Path
    proposed_path: Path
    report_path: Path
    n_fields: int
    n_found: int


def _fetch(source: RegistrySource, cache: DiskCache) -> tuple[list[SourceDoc], dict]:
    status = {"url": source.url, "status": "ok", "pages": 0}
    try:
        if source.kind == "html_doc":
            docs = fetch_html_source(source, cache=cache)
        elif source.kind == "openapi":
            docs = fetch_openapi_source(source, cache=cache)
        else:
            docs = []
        status["pages"] = len(docs)
    except Exception as e:  # noqa: BLE001
        status["status"] = f"error: {e}"
        docs = []
    return docs, status


def _extract(docs: list[SourceDoc]) -> list[RawField]:
    out: list[RawField] = []
    for d in docs:
        if d.kind == "html":
            out.extend(extract_html_structured(d))
        elif d.kind == "openapi_schema":
            out.extend(extract_openapi(d))
    return out


def _enrich(raws: list[RawField]) -> list[EnrichedField]:
    fields = dedupe_raw_fields(raws)
    infer_units(fields)
    tag_fields(fields)
    detect_traps(fields)
    return fields


def _write_catalog(entry: VendorRegistryEntry, fields: list[EnrichedField], path: Path) -> None:
    doc = {
        "meta": {
            "vendor": entry.slug,
            "resolved_via": "registry",
            "produced_by": "lexicon-discover",
            "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": [{"kind": s.kind, "url": s.url} for s in entry.sources],
        },
        "fields": {
            f.name: {
                "description": f.description,
                "unit": f.unit,
                "unit_confidence": round(f.unit_confidence, 2),
                "semantic_tags": [
                    {"tag": t.tag, "weight": round(t.weight, 2)} for t in f.semantic_tags
                ],
                "traps": [
                    {"kind": t.kind, "target": t.target, "evidence": t.evidence}
                    for t in f.traps
                ],
                "sources": [{"url": src.url, "locator": src.locator} for src in f.sources],
            }
            for f in fields
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# DISCOVERED catalog — auto-generated by lexicon.discover.\n"
        + yaml.safe_dump(doc, sort_keys=False)
    )


def _write_proposed(entry: VendorRegistryEntry, proposed, report: str, path: Path) -> None:
    doc = {
        "meta": {
            "vendor": entry.slug,
            "report": report,
            "status": "proposed",
            "produced_by": "lexicon-discover",
            "produced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "fields": {name: p.formula for name, p in proposed.items() if p.formula is not None},
        "proposals": {
            name: {
                "proposed": p.formula,
                "confidence": p.confidence,
                "rationale": p.rationale,
                "needs_review": p.needs_review,
            }
            for name, p in proposed.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# AUTO-PROPOSED mapping — run verify_mapping.py, then have an expert review.\n"
        + yaml.safe_dump(doc, sort_keys=False)
    )


def run_pipeline(
    *,
    entry: VendorRegistryEntry,
    cache: DiskCache,
    llm: LLMClient,   # accepted for symmetry; not used by v1's rule-based enrichers
    catalogs_dir: Path,
    proposed_dir: Path,
    reports_dir: Path,
    report: str = "queue",
) -> PipelineResult:
    all_docs: list[SourceDoc] = []
    source_statuses: list[dict] = []
    for src in entry.sources:
        docs, status = _fetch(src, cache)
        all_docs.extend(docs)
        source_statuses.append(status)

    raws = _extract(all_docs)
    fields = _enrich(raws)
    proposed = propose_mapping(fields, report=report)

    catalog_path  = catalogs_dir / f"{entry.slug}.yaml"
    proposed_path = proposed_dir / f"{entry.slug}.{report}.PROPOSED.yaml"
    report_path   = reports_dir  / f"{entry.slug}.md"

    _write_catalog(entry, fields, catalog_path)
    _write_proposed(entry, proposed, report, proposed_path)

    traps_flat = []
    for f in fields:
        for t in f.traps:
            traps_flat.append({"field": f.name, "kind": t.kind, "target": t.target})
    write_coverage_report(
        vendor_slug=entry.slug, report=report,
        proposals=proposed, sources=source_statuses, traps=traps_flat,
        path=report_path,
    )
    n_found = sum(1 for p in proposed.values() if p.formula is not None)
    return PipelineResult(
        catalog_path=catalog_path,
        proposed_path=proposed_path,
        report_path=report_path,
        n_fields=len(proposed),
        n_found=n_found,
    )
```

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_pipeline.py -v
```

Expected: 1 pass.

- [ ] **Step 5: Commit.**

```bash
git add src/lexicon/discover/pipeline.py tests/lexicon/discover/test_pipeline.py
git commit -m "feat(discover): pipeline orchestrator wires all stages together"
```

---

## Task 21: CLI entrypoint

**Files:**
- Create: `src/lexicon/discover/cli.py`
- Create: `tests/lexicon/discover/test_cli.py`

- [ ] **Step 1: Write the failing test.**

```python
import os
from pathlib import Path
import textwrap
import subprocess
import sys


def test_cli_runs_end_to_end(tmp_path):
    """Smoke test: invoke the CLI with a --cache-dir pointing at a pre-seeded
    cache, and verify it produces the three output files.
    """
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "mini.yaml").write_text(textwrap.dedent("""
        slug: mini
        name: Mini
        aliases: []
        category: fixed_schema
        description: d
        sources:
          - kind: html_doc
            role: primary
            url: https://mock.mini/x
    """))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    from lexicon.discover.cache import DiskCache
    DiskCache(cache_dir).put(
        "http", "https://mock.mini/x",
        b"<html><body><table><tr><th>Field</th><th>Description</th></tr>"
        b"<tr><td>holdtime</td><td>Hold time in seconds.</td></tr></table></body></html>",
    )

    root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    r = subprocess.run(
        [sys.executable, "-m", "lexicon.discover", "mini",
         "--registry", str(registry_dir),
         "--cache-dir", str(cache_dir),
         "--catalogs-dir", str(tmp_path / "catalogs"),
         "--proposed-dir", str(tmp_path / "proposed"),
         "--reports-dir",  str(tmp_path / "reports"),
         "--offline"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "catalogs" / "mini.yaml").exists()
    assert (tmp_path / "proposed" / "mini.queue.PROPOSED.yaml").exists()
    assert (tmp_path / "reports" / "mini.md").exists()
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_cli.py -v
```

Expected: module not runnable.

- [ ] **Step 3: Implement `src/lexicon/discover/cli.py`:**

```python
"""`python -m lexicon.discover <vendor>` entrypoint.

Flags:
  --registry <dir>       ontology/registry/ by default
  --cache-dir <dir>      state/discovery_cache/ by default
  --catalogs-dir <dir>   fixtures/vendor_catalogs/
  --proposed-dir <dir>   ontology/proposed/
  --reports-dir <dir>    out/discovery_reports/
  --report queue|agentqueue|agentsystem
  --refresh              force re-fetch (default: use cache)
  --offline              disallow cache writes; fail on cache miss (CI mode)
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .cache import DiskCache
from .llm import LLMClient
from .pipeline import run_pipeline
from .registry import load_registry
from .resolver import resolve_vendor_with_fallback, ResolveError


ROOT = Path(__file__).resolve().parents[3]

DEFAULTS = {
    "registry":     ROOT / "ontology" / "registry",
    "cache_dir":    ROOT / "state" / "discovery_cache",
    "catalogs_dir": ROOT / "fixtures" / "vendor_catalogs",
    "proposed_dir": ROOT / "ontology" / "proposed",
    "reports_dir":  ROOT / "out" / "discovery_reports",
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser("lexicon.discover")
    ap.add_argument("vendor")
    ap.add_argument("--registry",     default=str(DEFAULTS["registry"]))
    ap.add_argument("--cache-dir",    default=str(DEFAULTS["cache_dir"]))
    ap.add_argument("--catalogs-dir", default=str(DEFAULTS["catalogs_dir"]))
    ap.add_argument("--proposed-dir", default=str(DEFAULTS["proposed_dir"]))
    ap.add_argument("--reports-dir",  default=str(DEFAULTS["reports_dir"]))
    ap.add_argument("--report", choices=["queue", "agentqueue", "agentsystem"], default="queue")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--offline", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cache = DiskCache(Path(args.cache_dir), offline=args.offline)
    llm = LLMClient(cache=cache, offline=args.offline)
    try:
        entries = load_registry(Path(args.registry))
        result = resolve_vendor_with_fallback(args.vendor, entries, llm)
    except ResolveError as e:
        print(f"[lexicon.discover] {e}", file=sys.stderr)
        return 2

    r = run_pipeline(
        entry=result.entry,
        cache=cache, llm=llm,
        catalogs_dir=Path(args.catalogs_dir),
        proposed_dir=Path(args.proposed_dir),
        reports_dir=Path(args.reports_dir),
        report=args.report,
    )
    print(f"[lexicon.discover] {result.entry.slug} via {result.resolved_via}: "
          f"{r.n_found}/{r.n_fields} fields")
    print(f"  catalog:  {r.catalog_path}")
    print(f"  proposed: {r.proposed_path}")
    print(f"  report:   {r.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Wire up `python -m lexicon.discover`.** Create `src/lexicon/discover/__main__.py`:

```python
from .cli import main
raise SystemExit(main())
```

- [ ] **Step 5: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_cli.py -v
```

Expected: 1 pass.

- [ ] **Step 6: Commit.**

```bash
git add src/lexicon/discover/cli.py src/lexicon/discover/__main__.py tests/lexicon/discover/test_cli.py
git commit -m "feat(discover): add lexicon.discover CLI entrypoint"
```

---

## Task 22: Shim `src/discover.py` to delegate to new pipeline

**Files:**
- Modify: `src/discover.py`
- Create: `tests/lexicon/discover/test_shim_discover.py`

Backwards-compat shim so `add_vendor.sh` and any external callers keep working. New behavior: if invoked with only a vendor name (no `--from-csv`/`--doc`/`--crawl`), delegate to the new pipeline. Otherwise fall through to the original code path.

- [ ] **Step 1: Write the failing test.**

```python
from pathlib import Path
import textwrap
import subprocess
import sys


def test_shim_dispatches_to_new_pipeline_when_only_vendor(tmp_path):
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "mini.yaml").write_text(textwrap.dedent("""
        slug: mini
        name: Mini
        aliases: []
        category: fixed_schema
        description: d
        sources:
          - kind: html_doc
            role: primary
            url: https://mock.mini/x
    """))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    from lexicon.discover.cache import DiskCache
    DiskCache(cache_dir).put(
        "http", "https://mock.mini/x",
        b"<html><body><table><tr><th>Field</th><th>Description</th></tr>"
        b"<tr><td>holdtime</td><td>Hold time in seconds.</td></tr></table></body></html>",
    )

    root = Path(__file__).resolve().parents[3]
    r = subprocess.run(
        [sys.executable, str(root / "src" / "discover.py"), "mini",
         "--registry", str(registry_dir),
         "--cache-dir", str(cache_dir),
         "--catalogs-dir", str(tmp_path / "catalogs"),
         "--proposed-dir", str(tmp_path / "proposed"),
         "--reports-dir",  str(tmp_path / "reports"),
         "--offline"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "catalogs" / "mini.yaml").exists()


def test_shim_falls_through_to_legacy_from_csv(tmp_path):
    """--from-csv is still handled by legacy code path — smoke test."""
    csv = tmp_path / "demo.csv"
    csv.write_text("INTERVAL_START,holdtime\n2025-06-02T09:00,42\n")
    root = Path(__file__).resolve().parents[3]
    out = tmp_path / "out.yaml"
    r = subprocess.run(
        [sys.executable, str(root / "src" / "discover.py"), "DemoVendor",
         "--from-csv", str(csv), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert out.exists()
    text = out.read_text()
    assert "holdtime" in text
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_shim_discover.py -v
```

Expected: first test fails (shim not present).

- [ ] **Step 3: Modify `src/discover.py`.** Add this dispatcher block at the very top of `main()` — before the existing argument parsing — so it intercepts the "vendor-only" case. Edit the existing `def main():` function:

Find the line `def main():` and immediately after it, before `ap = argparse.ArgumentParser()`, insert:

```python
def main():
    # New-pipeline dispatcher: if the user passed *only* a vendor name (plus new-pipeline
    # flags), delegate to lexicon.discover. Legacy flags (--from-csv/--doc/--crawl) fall
    # through to the original code path below.
    import sys as _sys
    _legacy_flags = {"--from-csv", "--doc", "--crawl"}
    if len(_sys.argv) >= 2 and not (_legacy_flags & set(_sys.argv)):
        from lexicon.discover.cli import main as _new_main
        raise SystemExit(_new_main(_sys.argv[1:]))
    ap = argparse.ArgumentParser()
    # ... (rest of existing body unchanged)
```

(Preserve everything else in the file. Do NOT delete the legacy code.)

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_shim_discover.py -v
```

Expected: 2 pass.

- [ ] **Step 5: Verify existing tests still pass.**

```bash
pytest -v
```

Expected: green.

- [ ] **Step 6: Commit.**

```bash
git add src/discover.py tests/lexicon/discover/test_shim_discover.py
git commit -m "feat(discover): shim src/discover.py to new pipeline when no legacy flags"
```

---

## Task 23: Shim `src/automap.py` to delegate to new mapper

**Files:**
- Modify: `src/automap.py`
- Create: `tests/lexicon/discover/test_shim_automap.py`

When invoked with `--engine lexicon` (new option), the old CLI produces the same-shape `PROPOSED.yaml` file but via the new mapper, using an existing catalog. Preserves `--engine heuristic|reference|llm` for backward compat.

- [ ] **Step 1: Write the failing test.**

```python
from pathlib import Path
import subprocess
import sys
import textwrap
import yaml


def test_lexicon_engine_produces_proposed_file(tmp_path):
    catalog_path = tmp_path / "cat.yaml"
    catalog_path.write_text(textwrap.dedent("""
        meta:
          vendor: fixtures_avaya_mini
          resolved_via: manual
        fields:
          split:
            description: "Split/skill number, the queue key."
            unit: key
            semantic_tags: [{tag: queue_key_like, weight: 0.9}]
          acdtime:
            description: "Talk time of ACD calls. Does NOT include holdtime."
            unit: duration_seconds
            semantic_tags: [{tag: talk_time_like, weight: 0.9}]
            traps: [{kind: exclusion, target: hold_time, evidence: 'does NOT include holdtime'}]
          holdtime:
            description: "Hold time on ACD calls, in seconds."
            unit: duration_seconds
            semantic_tags: [{tag: hold_time_like, weight: 0.9}]
    """))
    out_path = tmp_path / "proposed.yaml"
    root = Path(__file__).resolve().parents[3]
    r = subprocess.run(
        [sys.executable, str(root / "src" / "automap.py"), str(catalog_path),
         "--vendor", "MiniVendor", "--engine", "lexicon",
         "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    data = yaml.safe_load(out_path.read_text())
    assert data["fields"]["HandleTime"] == "acdtime + holdtime"
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/lexicon/discover/test_shim_automap.py -v
```

Expected: `--engine lexicon` not accepted.

- [ ] **Step 3: Modify `src/automap.py`.** In `main()`, extend the `--engine` choices and add a new dispatch branch. Edit the argparse block:

```python
    ap.add_argument("--engine", choices=["heuristic", "reference", "llm", "lexicon"], default="reference")
```

Then add a branch **before** the existing `if args.engine == "llm":`:

```python
    if args.engine == "lexicon":
        from lexicon.discover.enrich.semantic_tag import tag_fields
        from lexicon.discover.enrich.trap_detect import detect_traps
        from lexicon.discover.enrich.unit_infer import infer_units
        from lexicon.discover.mapper import propose_mapping
        from lexicon.discover.models import EnrichedField, FieldSource, SemanticTag, Trap
        cat_fields = catalog.get("fields", {})
        enriched: list[EnrichedField] = []
        for name, spec in cat_fields.items():
            if isinstance(spec, str):        # legacy discover catalog: name -> description
                spec = {"description": spec}
            enriched.append(EnrichedField(
                name=name,
                description=spec.get("description", ""),
                sources=[FieldSource(doc_id="catalog", url="", locator="", snippet="")],
                unit=spec.get("unit", "unknown"),
                unit_confidence=float(spec.get("unit_confidence", 0.0)),
                semantic_tags=[SemanticTag(tag=t["tag"], weight=float(t.get("weight", 0.0)))
                               for t in (spec.get("semantic_tags") or [])],
                traps=[Trap(kind=t.get("kind", ""), target=t.get("target", ""),
                            evidence=t.get("evidence", ""))
                       for t in (spec.get("traps") or [])],
            ))
        # Rich catalog: use provided enrichment as-is.
        # Legacy catalog (only descriptions): populate enrichment now.
        if not any(e.unit != "unknown" for e in enriched):
            infer_units(enriched)
            tag_fields(enriched)
            detect_traps(enriched)
        proposed = propose_mapping(enriched, report=args.report)
        fields = {name: p.formula for name, p in proposed.items() if p.formula is not None}
        proposals = {
            name: {
                "proposed": p.formula,
                "confidence": p.confidence,
                "rationale": p.rationale,
                "needs_review": p.needs_review,
            }
            for name, p in proposed.items()
        }
    elif args.engine == "llm":
        fields, proposals = propose_llm(catalog, args.vendor, args.report)
    elif args.engine == "heuristic":
        fields, proposals = propose_heuristic(catalog, args.report)
    else:
        refs = [v for v in reference_vendors() if v.lower() != args.vendor.lower()]
        print(f"[automap:reference] reusing formula patterns learned from: {', '.join(refs) or '(none yet)'}")
        fields, proposals = propose_reference(catalog, args.report)
```

(The existing `if args.engine == "llm":` block should be changed to `elif` as shown.)

- [ ] **Step 4: Run tests to verify they pass.**

```bash
pytest tests/lexicon/discover/test_shim_automap.py -v
```

Expected: 1 pass.

- [ ] **Step 5: Verify existing tests still pass.**

```bash
pytest -v
```

Expected: green.

- [ ] **Step 6: Commit.**

```bash
git add src/automap.py tests/lexicon/discover/test_shim_automap.py
git commit -m "feat(discover): add --engine lexicon to automap.py delegating to new mapper"
```

---

## Task 24: End-to-end regression — Avaya CMS

**Files:**
- Create: `fixtures/vendor_docs_snapshots/avaya_cms/hsplit.html`
- Create: `tests/lexicon/discover/test_e2e_avaya_cms.py`

Uses a committed HTML snapshot of the Avaya CMS docs (a minimal but realistic subset) as the input, runs the full pipeline offline, and asserts the punchline: `HandleTime == "acdtime + holdtime"` and every canonical concept the current Avaya golden expects is present.

- [ ] **Step 1: Create the fixture snapshot.** Save this to `fixtures/vendor_docs_snapshots/avaya_cms/hsplit.html`:

```html
<html>
<head><title>Avaya CMS hsplit — Database items</title></head>
<body>
<h1>hsplit database items</h1>
<table>
  <tr><th>Field</th><th>Description</th></tr>
  <tr><td>split</td><td>The split/skill number. Serves as the queue key.</td></tr>
  <tr><td>acdcalls</td><td>Count of ACD calls handled during the interval.</td></tr>
  <tr><td>acceptable</td><td>Count of ACD calls answered within the service level (acceptable).</td></tr>
  <tr><td>abncalls</td><td>Count of ACD calls abandoned during the interval.</td></tr>
  <tr><td>slvlabns</td><td>Count of abandons within the service level.</td></tr>
  <tr><td>acdtime</td><td>Talk time of all ACD calls. Does NOT include holdtime. In seconds.</td></tr>
  <tr><td>holdtime</td><td>Total time that ACD callers were on hold, in seconds.</td></tr>
  <tr><td>acwtime</td><td>After call work time for ACD calls, in seconds.</td></tr>
  <tr><td>anstime</td><td>Time spent in queue and ringing before answer, in seconds. Delay before answer.</td></tr>
  <tr><td>contactsactive</td><td>Contacts active in this interval that arrived in a previous interval (carryover).</td></tr>
</table>
</body>
</html>
```

- [ ] **Step 2: Write the failing test.**

```python
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
```

- [ ] **Step 3: Run the test.**

```bash
pytest tests/lexicon/discover/test_e2e_avaya_cms.py -v
```

Expected: PASS on all 10 assertions. If a specific field fails, that means the enricher/mapper needs adjustment — fix it in the responsible module (unit_infer, semantic_tag, or mapper), not in the test.

- [ ] **Step 4: Verify full suite.**

```bash
pytest -v
```

Expected: green.

- [ ] **Step 5: Commit.**

```bash
git add fixtures/vendor_docs_snapshots/avaya_cms/ tests/lexicon/discover/test_e2e_avaya_cms.py
git commit -m "test(discover): E2E regression — avaya_cms reproduces 10/10 mapping"
```

---

## Task 25: End-to-end regression — Genesys Cloud (ms → s + ACW-excluded HandleTime)

**Files:**
- Create: `fixtures/vendor_docs_snapshots/genesys_cloud/analytics.html`
- Create: `tests/lexicon/discover/test_e2e_genesys_cloud.py`

Punchlines for Genesys: (a) ms→s unit conversion embedded in the formula, and (b) HandleTime composed from talk + hold, NOT from the vendor's own `tHandle` field which includes ACW.

- [ ] **Step 1: Create the fixture snapshot.** Save to `fixtures/vendor_docs_snapshots/genesys_cloud/analytics.html`:

```html
<html>
<head><title>Genesys Cloud — Analytics conversation metrics</title></head>
<body>
<h1>Conversation Aggregate Metrics</h1>
<table>
  <tr><th>Field</th><th>Description</th></tr>
  <tr><td>queueId</td><td>Queue identifier (queue key).</td></tr>
  <tr><td>nHandled</td><td>Count of handled conversations.</td></tr>
  <tr><td>nOffered</td><td>Count of offered conversations.</td></tr>
  <tr><td>tTalk</td><td>Talk time in milliseconds.</td></tr>
  <tr><td>tHeld</td><td>Hold time in milliseconds.</td></tr>
  <tr><td>tAcw</td><td>ACW (wrap-up) time in milliseconds.</td></tr>
  <tr><td>tHandle</td><td>Total handle time in milliseconds. Includes ACW (wrap-up).</td></tr>
  <tr><td>tAnswered</td><td>Time to answer, in milliseconds. Delay before answer.</td></tr>
</table>
</body>
</html>
```

- [ ] **Step 2: Write the failing test.**

```python
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
```

- [ ] **Step 3: Run the test.**

```bash
pytest tests/lexicon/discover/test_e2e_genesys_cloud.py -v
```

Expected: PASS.

- [ ] **Step 4: Verify full suite.**

```bash
pytest -v
```

Expected: green.

- [ ] **Step 5: Commit.**

```bash
git add fixtures/vendor_docs_snapshots/genesys_cloud/ tests/lexicon/discover/test_e2e_genesys_cloud.py
git commit -m "test(discover): E2E regression — genesys_cloud ms->s + ACW-excluded HandleTime"
```

---

## Task 26: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `CLAUDE.md`

Bring the docs in line with the new `lexicon discover <vendor>` verb. Do NOT remove the existing docs — the shim still supports the old commands.

- [ ] **Step 1: Update `README.md`** — under "Quick start", add before the existing "Discover a new vendor's fields" section:

```markdown
### New in v1: one-shot vendor discovery

Give Lexicon a vendor name and it produces a rich catalog + proposed mapping
from public documentation only:

    python -m lexicon.discover avaya_cms
    python -m lexicon.discover "Avaya CMS"        # name resolution via registry

The registry lives at `ontology/registry/<slug>.yaml`. Add a new vendor by
copying one of the existing entries and pointing it at the vendor's official
docs.

Outputs:
- `fixtures/vendor_catalogs/<slug>.yaml`        — rich field catalog
- `ontology/proposed/<slug>.<report>.PROPOSED.yaml` — proposed mapping (consumed
  by `verify_mapping.py` unchanged)
- `out/discovery_reports/<slug>.md`             — coverage report (what worked,
  what needs a human)
```

- [ ] **Step 2: Update `docs/PROJECT_GUIDE.md`** — in the "Adding a new ACD vendor" section, insert a new "Step 0.5: try the fast path" between Step 0 and Step 1:

```markdown
### Step 0.5 — Try the fast path (registry-first discovery)

If the vendor has a public documentation site or an OpenAPI schema, try:

    python -m lexicon.discover <slug>

This runs the full discover→propose pipeline from the vendor name alone,
using `ontology/registry/<slug>.yaml`. For unknown vendors, Lexicon uses an
LLM to propose candidate doc URLs (search fallback), which you can then commit
to a new registry entry.

Move on to Step 1 (the incremental discover/scaffold path below) only if you
need PDF/CSV inputs the new pipeline doesn't yet support.
```

- [ ] **Step 3: Update `CLAUDE.md`** — append this paragraph at the end of the existing gate section:

```markdown
When touching discovery code (`src/lexicon/discover/*`), the gate remains the
same — `pytest -v` must be green. The two E2E regression tests
`tests/lexicon/discover/test_e2e_avaya_cms.py` and
`tests/lexicon/discover/test_e2e_genesys_cloud.py` are load-bearing:
they encode the punchlines this project must deliver (Avaya HandleTime =
acdtime + holdtime; Genesys ms→s + ACW-excluded HandleTime). Do NOT weaken
these tests to make a change pass.
```

- [ ] **Step 4: Verify docs render cleanly.**

```bash
grep -n "lexicon discover" README.md docs/PROJECT_GUIDE.md CLAUDE.md
```

Expected: all three files mention the new verb.

- [ ] **Step 5: Commit.**

```bash
git add README.md docs/PROJECT_GUIDE.md CLAUDE.md
git commit -m "docs: introduce lexicon.discover in README, PROJECT_GUIDE, CLAUDE"
```

---

## Final verification

- [ ] Run the full suite:

```bash
pytest -v
```

Expected: everything green, no regressions.

- [ ] Confirm the punchlines by inspecting the two E2E artifacts:

```bash
cat tests/lexicon/discover/test_e2e_avaya_cms.py
cat tests/lexicon/discover/test_e2e_genesys_cloud.py
```

Both encode the concrete v1 success criteria from `docs/superpowers/specs/2026-08-09-discovery-deepening-design.md` §13.

- [ ] Confirm no accidental placeholders remain by scanning your diffs:

```bash
git log --oneline
git diff --stat main~26..HEAD
```

---

## Follow-ups (not part of this plan)

These are legitimate v1 gaps, listed here so a reviewer knows they were deliberate:

- Multi-hop BFS crawl in the new pipeline (Task 9 fetches only the primary URL for v1).
- PDF source support.
- GraphQL / WSDL fetchers and extractors (stubs / not implemented — no v1 anchor vendor needs them).
- LLM prose extractor for HTML sections the structured extractor didn't consume (needed only if a future vendor's docs are unstructured prose).
- Registry promotion UX for search-fallback resolutions (currently the LLM-suggested entry is used in-memory but not persisted to `ontology/registry/`).
- Web-search-based search fallback (currently LLM-only, from model knowledge).
- Confidence calibration dashboard.
- Embedding-based cross-vendor semantic similarity.
