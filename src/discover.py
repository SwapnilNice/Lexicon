"""
Lexicon DISCOVER — step 1 of adding a vendor.

Turns a vendor's document (or a data export) into a field catalog YAML, so you
DON'T hand-write it. The catalog is the input the auto-mapper reasons over.

Inputs (any combination):
  --from-csv <file>   : use the CSV/TSV header row as the vendor's field names
                        (great when you have a real export — no LLM needed).
  --doc <file|url>    : a vendor doc (.txt/.md/.html/.pdf, or a URL) to read
                        field names + descriptions from.
  --engine auto|llm   : 'auto' (default, offline) parses obvious structures;
                        'llm' asks a model to extract fields+descriptions (needs
                        the anthropic SDK + ANTHROPIC_API_KEY).

Output: fixtures/vendor_catalogs/<vendor>.yaml   (meta.source + fields).

Usage:
  python src/discover.py <Vendor> --from-csv path/to/export.csv
  python src/discover.py <Vendor> --doc path/to/vendor_doc.pdf --engine llm
"""
import argparse
import csv
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------- read the document into plain text ----------
def read_source(src: str) -> str:
    if re.match(r"^https?://", src):
        with urllib.request.urlopen(src, timeout=30) as r:   # runs on your machine
            data = r.read().decode("utf-8", "ignore")
        return strip_html(data)
    path = pathlib.Path(src)
    ext = path.suffix.lower()
    if ext == ".pdf":
        return pdf_text(path)
    text = path.read_text(errors="ignore")
    return strip_html(text) if ext in (".html", ".htm") else text


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", s)
    return re.sub(r"<[^>]+>", " ", s)


def pdf_text(path: pathlib.Path) -> str:
    try:
        return subprocess.run(["pdftotext", "-layout", str(path), "-"],
                              capture_output=True, text=True, check=True).stdout
    except Exception:  # noqa: BLE001
        try:
            import pypdf  # type: ignore
            return "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(str(path)).pages)
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"[discover] cannot read PDF ({e}). Install poppler (pdftotext) or pypdf.")


def _canonical_url(url: str) -> str:
    """Strip fragment, lowercase host, drop trailing slash on non-root paths."""
    p = urllib.parse.urlparse(url)
    host = p.netloc.lower()
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urllib.parse.urlunparse((p.scheme.lower(), host, path, p.params, p.query, ""))


def _slugify_url(url: str) -> str:
    """Deterministic filesystem-safe slug for a URL. Bounded at 120 chars."""
    p = urllib.parse.urlparse(url)
    raw = f"{p.netloc}{p.path}"
    if p.query:
        raw += f"_{p.query}"
    slug = re.sub(r"[^a-z0-9._-]+", "_", raw.lower()).strip("_") or "root"
    return slug[:120]


USER_AGENT = "Lexicon-discover/1.0"


def _fetch_one(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Fetch a single URL. Returns (body_bytes, content_type). Raises on non-2xx."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        ctype = r.headers.get("Content-Type", "").lower()
    return body, ctype


_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def _extract_links(html: str, base_url: str) -> list[str]:
    """Regex link extraction. Drops mailto/javascript/anchor-only, resolves relative."""
    out = []
    for raw in _HREF_RE.findall(html):
        raw = raw.strip()
        if not raw or raw.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        out.append(urllib.parse.urljoin(base_url, raw))
    return out


def _chunk_text(text: str, size: int = 10_000) -> list[str]:
    """Split on paragraph boundaries into pieces close to `size` chars."""
    if len(text) <= size:
        return [text]
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) + 2 > size:
            chunks.append(buf); buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


def _merge_field_maps(a: dict, b: dict) -> dict:
    """Merge two {name: description} dicts. Non-empty wins over empty; longer wins."""
    out = dict(a)
    for name, desc in b.items():
        cur = out.get(name, "")
        if not cur and desc:
            out[name] = desc
        elif desc and len(desc) > len(cur):
            out[name] = desc
    return out


def _load_robots(site_root: str) -> urllib.robotparser.RobotFileParser:
    """Load and parse robots.txt for the given site root. Errors -> permissive parser."""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(urllib.parse.urljoin(site_root, "/robots.txt"))
    try:
        rp.read()
    except Exception:  # noqa: BLE001
        pass  # missing robots.txt = allow everything
    return rp


def crawl_site(seed: str, max_depth: int, max_pages: int,
               cache_dir: pathlib.Path, refresh: bool = False,
               ) -> list[tuple[str, pathlib.Path]]:
    """BFS same-host crawler. Returns ordered list of (canonical_url, cached_path)."""
    if not re.match(r"^https?://", seed):
        raise SystemExit("--crawl needs an http(s) URL")

    cache_dir.mkdir(parents=True, exist_ok=True)
    seed = _canonical_url(seed)
    parsed = urllib.parse.urlparse(seed)
    host = parsed.netloc
    site_root = f"{parsed.scheme}://{host}"
    robots = _load_robots(site_root)

    queue: list[tuple[str, int]] = [(seed, 0)]
    seen: set[str] = {seed}
    out: list[tuple[str, pathlib.Path]] = []

    while queue and len(out) < max_pages:
        url, depth = queue.pop(0)
        if not robots.can_fetch(USER_AGENT, url):
            continue

        slug = _slugify_url(url)
        html_path = cache_dir / f"{slug}.html"
        pdf_path = cache_dir / f"{slug}.pdf"
        cached = html_path if html_path.exists() else (pdf_path if pdf_path.exists() else None)

        if refresh or cached is None:
            try:
                body, ctype = _fetch_one(url)
            except Exception as e:  # noqa: BLE001
                print(f"[discover] skip {url}: {e}"); continue
            if "html" in ctype:
                path = html_path
            elif "pdf" in ctype:
                path = pdf_path
            else:
                continue  # not an HTML or PDF page
            path.write_bytes(body)
            time.sleep(0.5)
        else:
            path = cached

        out.append((url, path))
        if depth >= max_depth:
            continue
        if path.suffix != ".html":
            continue  # only follow links from HTML pages
        html = path.read_text(errors="ignore")
        for link in _extract_links(html, url):
            cu = _canonical_url(link)
            if urllib.parse.urlparse(cu).netloc != host:
                continue
            if cu in seen:
                continue
            seen.add(cu)
            queue.append((cu, depth + 1))

    return out


def _page_text(path: pathlib.Path) -> str:
    """Read a cached page (HTML or PDF) and return plain text."""
    if path.suffix == ".pdf":
        try:
            return pdf_text(path)
        except SystemExit:
            return ""  # PDF tools not available; skip this page rather than abort
    return strip_html(path.read_text(errors="ignore"))


def fields_from_pages_llm(pages: list[tuple[str, pathlib.Path]], vendor: str) -> dict:
    """Concatenate cached pages, chunk, run fields_from_text_llm per chunk, merge."""
    text = "\n\n===\n\n".join(_page_text(p) for _, p in pages)
    merged: dict = {}
    for chunk in _chunk_text(text):
        partial = fields_from_text_llm(chunk, vendor)
        merged = _merge_field_maps(merged, partial)
    return merged


# ---------- extract fields ----------
def fields_from_csv(path: str) -> dict:
    with open(path, newline="") as f:
        header = next(csv.reader(f))
    return {h.strip(): "" for h in header if h.strip() and h.strip().upper() != "INTERVAL_START"}


def fields_from_text_auto(text: str) -> dict:
    """Best-effort offline parse: pick 'name: description' / 'name - description'
    lines, and code-like tokens. Not perfect — use --engine llm for real docs."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z][\w./]{1,40})\s*[:\-–]\s+(.{3,200})$", line.strip())
        if m:
            name, desc = m.group(1), m.group(2).strip()
            if not re.search(r"\s", name):
                out.setdefault(name, desc)
    return out


def fields_from_text_llm(text: str, vendor: str) -> dict:
    prompt = (
        f"Extract the {vendor} data field names and a one-line description for each, "
        f"from this documentation. Return ONLY YAML: a top-level `fields:` map of "
        f"fieldName: \"description\". Text:\n\n{text[:12000]}")
    try:
        import os
        import anthropic  # type: ignore
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic()
        msg = client.messages.create(model="claude-sonnet-5", max_tokens=3000,
                                     messages=[{"role": "user", "content": prompt}])
        data = yaml.safe_load(msg.content[0].text)
        return data.get("fields", {})
    except Exception as e:  # noqa: BLE001
        # No key / SDK: write the prompt so you can run it in Claude Code instead.
        pf = ROOT / "ontology" / "proposed" / f"{vendor.lower()}.discover_prompt.txt"
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(prompt)
        print(f"[discover] LLM not available ({e}). Wrote a prompt to {pf}\n"
              f"          Paste it into Claude Code to get the fields, or use --from-csv.")
        return {}


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
    ap.add_argument("vendor")
    ap.add_argument("--from-csv", dest="csv", default=None)
    ap.add_argument("--doc", default=None)
    ap.add_argument("--crawl", default=None, help="Seed URL to crawl (http/https).")
    ap.add_argument("--max-depth", type=int, default=2)
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--refresh", action="store_true",
                    help="Ignore cache under fixtures/vendor_docs/<vendor>/.")
    ap.add_argument("--cache-dir", default=None,
                    help="Override cache dir (default: fixtures/vendor_docs/<vendor>/).")
    ap.add_argument("--engine", choices=["auto", "llm"], default="auto")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if not args.csv and not args.doc and not args.crawl:
        sys.exit("give --from-csv <file> and/or --doc <file|url> and/or --crawl <url>")
    if args.max_depth < 0 or args.max_pages < 1:
        sys.exit("--max-depth must be >=0 and --max-pages must be >=1")

    fields: dict = {}
    sources: list = []

    if args.csv:
        fields.update(fields_from_csv(args.csv))
        sources.append({"name": "data export header", "ref": args.csv})

    if args.crawl:
        cache_dir = pathlib.Path(args.cache_dir) if args.cache_dir else \
            ROOT / "fixtures" / "vendor_docs" / args.vendor.lower()
        print(f"[discover] crawling {args.crawl} (host-only, depth<={args.max_depth}, "
              f"pages<={args.max_pages}) -> cache {cache_dir}")
        pages = crawl_site(args.crawl, args.max_depth, args.max_pages, cache_dir, args.refresh)
        if not pages:
            sys.exit(f"[discover] crawl fetched 0 pages; check {cache_dir}")
        if args.engine == "llm":
            crawl_fields = fields_from_pages_llm(pages, args.vendor)
        else:
            text = "\n\n===\n\n".join(_page_text(p) for _, p in pages)
            crawl_fields = fields_from_text_auto(text)
        for k, v in crawl_fields.items():
            if v or k not in fields:
                fields[k] = v or fields.get(k, "")
        for url, p in pages:
            sources.append({"name": p.stem, "url": url})

    if args.doc:
        text = read_source(args.doc)
        doc_fields = fields_from_text_llm(text, args.vendor) if args.engine == "llm" \
            else fields_from_text_auto(text)
        for k, v in doc_fields.items():
            if v or k not in fields:
                fields[k] = v or fields.get(k, "")
        sources.append({"name": "vendor documentation",
                        "url" if re.match(r"^https?://", args.doc) else "ref": args.doc})

    doc = {"meta": {"vendor": args.vendor, "report": "queue", "source": sources},
           "fields": fields}
    out = args.out or str(ROOT / "fixtures" / "vendor_catalogs" / f"{args.vendor.lower()}.yaml")
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    header = ("# DISCOVERED catalog (step 1). Review descriptions before mapping.\n"
              "# Empty descriptions = add them (or re-run with --doc/--engine llm).\n")
    pathlib.Path(out).write_text(header + yaml.safe_dump(doc, sort_keys=False))
    n_desc = sum(1 for v in fields.values() if v)
    print(f"[discover] {len(fields)} fields ({n_desc} with descriptions) -> {out}")
    print(f"           next:  ./add_vendor.sh {args.vendor} {out}")


if __name__ == "__main__":
    main()
