# discover.py — crawl mode

**Date:** 2026-07-15
**Author:** swapnil.zade@nice.com
**Status:** Approved for implementation

## Problem

`src/discover.py` (step 1 of adding a new vendor) can only read a single document
at a time: one local file, or one URL fetched with `urllib.request.urlopen`.
Vendor documentation for products like Avaya CMS or Genesys is spread across
dozens of linked HTML pages under a doc host. Today the operator has to either
find one giant PDF or hand-feed each URL. We want:

> "I give a vendor name and one seed URL. `discover.py` crawls the vendor's
> documentation site, extracts every field name + description it can find, and
> writes the same `fixtures/vendor_catalogs/<vendor>.yaml` the rest of Lexicon
> already consumes."

## Goals

1. New `--crawl <seed_url>` mode on `discover.py` that walks a vendor doc site
   and produces the same YAML catalog shape as today's `--doc` / `--from-csv`
   modes. No downstream tool (`automap.py`, `engine.py`, `sensor.py`) changes.
2. Safe defaults: bounded depth and page count; polite fetching (robots.txt +
   inter-request delay); no fetches outside the seed host.
3. Reproducibility: crawled pages cached to disk under
   `fixtures/vendor_docs/<vendor>/` so a re-run does not re-hit the vendor and
   reviewers can see exactly what the extractor read.
4. Extraction quality high enough to be worth using with `--engine llm`; regex
   fallback still available.

## Non-Goals

- No JavaScript-rendered pages (no headless browser). Operator falls back to
  `--from-csv` when the vendor doc is JS-only.
- No authenticated crawling. Public documentation only.
- No `sitemap.xml` discovery; BFS from the seed is sufficient.
- No parallelism. Sequential fetches keep the code simple and vendor-friendly.
- No change to the catalog YAML shape or to `automap.py` / `engine.py` /
  `sensor.py`.

## CLI

```
python src/discover.py <Vendor> \
    --crawl <seed_url> \
    [--max-depth 2] [--max-pages 30] \
    [--engine auto|llm] [--refresh] \
    [--out <path>]
```

- `--crawl` is additive with `--from-csv`. If both are given, CSV headers are
  the field set and crawl fills in descriptions.
- `--crawl` is mutually usable with `--doc`; if both are supplied, both feed
  into the same extraction pipeline (crawl pages first, then the doc).
- `--engine llm` is the recommended pairing with `--crawl`.
- `--refresh` bypasses the on-disk cache and re-fetches every page.
- Existing flags (`--from-csv`, `--doc`, `--engine`, `--out`) keep current
  behavior when `--crawl` is absent.

Refuse to run with any of:
- `--crawl` value that is not `http://` or `https://`.
- `--max-depth < 0` or `--max-pages < 1`.

## Architecture

### New / changed functions in `src/discover.py`

| Function | Purpose |
|---|---|
| `crawl_site(seed, max_depth, max_pages, cache_dir, refresh) -> list[Path]` | BFS crawler; returns ordered list of cached page paths. |
| `_canonical_url(url) -> str` | Strip fragment, normalize trailing slash, lowercase host. Used for dedup. |
| `_slugify_url(url) -> str` | Deterministic filename for cache (host + path, replace non-alnum with `_`, cap at 120 chars). |
| `_fetch_one(url) -> (bytes, content_type)` | Single fetch with a 30 s timeout and a `User-Agent: Lexicon-discover/1.0`. Raises on non-200. |
| `_extract_links(html, base_url) -> list[str]` | Regex-only link extraction (`href="..."` and `<a ...>`), resolved via `urllib.parse.urljoin`. |
| `_chunk_text(text, size=10_000) -> list[str]` | Split concatenated text on paragraph boundaries (`\n\n`) into chunks close to `size` chars. |
| `fields_from_pages_llm(paths, vendor) -> dict` | Read each cached page (HTML → `strip_html`, PDF → `pdf_text`), concatenate, chunk, call `fields_from_text_llm` per chunk, merge. |
| `main()` | Wire up `--crawl`, `--max-depth`, `--max-pages`, `--refresh`; call `crawl_site` then either `fields_from_pages_llm` (engine=llm) or `fields_from_text_auto` on the aggregated text. |

Existing functions kept as-is: `read_source`, `strip_html`, `pdf_text`,
`fields_from_csv`, `fields_from_text_auto`, `fields_from_text_llm`.

### Data flow

```
seed URL ─▶ crawl_site ─▶ [cached files in fixtures/vendor_docs/<vendor>/]
                             │
                             ▼
                     fields_from_pages_llm    (engine=llm)
                             │  or fields_from_text_auto on concatenated text (engine=auto)
                             ▼
                     {field: description}
                             │
                             ▼
              fixtures/vendor_catalogs/<vendor>.yaml
```

### Crawl algorithm

```
seed  = _canonical_url(seed_url)
host  = urlparse(seed).netloc
robot = urllib.robotparser.RobotFileParser(f"{scheme}://{host}/robots.txt")
robot.read()

queue = [(seed, depth=0)]
seen  = {seed}
out   = []

while queue and len(out) < max_pages:
    url, depth = queue.pop(0)
    if not robot.can_fetch("Lexicon-discover/1.0", url):   continue

    slug = _slugify_url(url)
    html_path, pdf_path = cache_dir / f"{slug}.html", cache_dir / f"{slug}.pdf"
    cached = html_path if html_path.exists() else (pdf_path if pdf_path.exists() else None)

    if refresh or cached is None:
        body, ctype = _fetch_one(url)                       # raises on non-200
        if   "html" in ctype:            path = html_path
        elif "pdf"  in ctype:            path = pdf_path
        else:                            continue           # skip other types
        path.write_bytes(body)
        sleep(0.5)                                          # politeness
    else:
        path = cached

    out.append(path)
    if depth >= max_depth:               continue
    if path.suffix != ".html":           continue           # only follow links from HTML
    for link in _extract_links(path.read_text(errors="ignore"), url):
        cu = _canonical_url(link)
        if urlparse(cu).netloc != host:  continue
        if cu in seen:                   continue
        seen.add(cu)
        queue.append((cu, depth + 1))

return out
```

### Extraction algorithm (LLM chunk + merge)

```
text = "\n\n".join(strip_html_or_pdf(p) for p in cached_pages)
merged: dict[str, str] = {}
for chunk in _chunk_text(text, size=10_000):
    partial = fields_from_text_llm(chunk, vendor)      # existing function
    for name, desc in partial.items():
        cur = merged.get(name, "")
        if not cur and desc: merged[name] = desc
        elif desc and len(desc) > len(cur): merged[name] = desc
return merged
```

Merge rule (locked in): non-empty description never overwritten by empty;
between two non-empty descriptions, the longer one wins.

### `meta.source` output

Each cached page becomes one entry:

```yaml
meta:
  vendor: <Vendor>
  report: queue
  source:
    - name: "<page <title> or slug>"
      url:  "<canonical URL>"
    - ...
```

Page title is extracted from `<title>...</title>` if present, else the URL slug.

## File / directory changes

| Path | Change |
|---|---|
| `src/discover.py` | Add functions + CLI flags described above. |
| `fixtures/vendor_docs/` | New directory. Per-vendor subdirs created on demand. |
| `.gitignore` | Add `fixtures/vendor_docs/` so cached HTML/PDF is not committed. |
| `tests/test_discover_crawl.py` | New unit tests (see Testing). |
| `README.md` | One new example line under the discover section. |

No changes to `automap.py`, `engine.py`, `sensor.py`, ontology YAML, or the
existing catalogs in `fixtures/vendor_catalogs/`.

## Error handling

- Non-http(s) seed → `SystemExit("--crawl needs an http(s) URL")`.
- `robots.txt` disallows the seed → `SystemExit` with the offending URL.
- Fetch returns non-200 → log and skip that URL; continue with the rest.
- Fetch raises (timeout, DNS, TLS) → log the URL + error, skip, continue.
- Content-Type not HTML or PDF → skip, do not count against `--max-pages`.
- PDF extraction fails (`pdftotext` and `pypdf` both unavailable) → skip that
  page with a warning; the run still succeeds for the other pages.
- LLM unavailable and `--engine llm` requested → today's behavior: write the
  prompt file to `ontology/proposed/<vendor>.discover_prompt.txt` for the first
  chunk, warn, and fall through to regex on the aggregated text.
- Zero fields extracted → exit 1 with a message pointing at the cache dir so
  the operator can inspect what was fetched.

## Testing

Unit tests in `tests/test_discover_crawl.py`. All tests use a fixture HTTP
server (`http.server.ThreadingHTTPServer`) or monkey-patched `urllib.request`
— no real network calls.

| Test | Asserts |
|---|---|
| `test_crawl_stops_at_max_pages` | Serve 50 linked pages; `--max-pages 10` fetches exactly 10. |
| `test_crawl_stops_at_max_depth` | Depth-3 chain; `--max-depth 1` fetches seed + first-level only. |
| `test_crawl_stays_on_host` | Seed links to `other.example.com`; that URL is never fetched. |
| `test_crawl_respects_robots_txt` | `robots.txt` disallows `/private/`; those URLs are skipped. |
| `test_crawl_dedup` | Two links point to same URL with different fragments; fetched once. |
| `test_crawl_uses_cache` | Second run with same args does not call `_fetch_one`. |
| `test_crawl_refresh_bypasses_cache` | `--refresh` re-invokes `_fetch_one` even if cache present. |
| `test_chunk_llm_merge_prefers_longer_description` | Two chunks disagree on a field's description; longer one wins. |
| `test_end_to_end_writes_catalog_yaml` | With a fake 3-page site, `discover.py --crawl` writes a YAML with the expected fields. |

`pytest -v` must pass. The existing pytest + sensor gate from `CLAUDE.md`
remains the definition of done.

## Rollout

- Purely additive. Nothing existing breaks — running `discover.py` without
  `--crawl` behaves exactly as before.
- No config, no migration, no data changes.

## Open questions

None. All decisions in this doc are final unless the implementation plan surfaces
a concrete blocker.
