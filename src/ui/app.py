"""
Lexicon — Vendor Onboarding UI (Streamlit)

Run:   streamlit run src/ui/app.py

Give it a vendor name + a URL (or upload a doc). It will:
  1. Fetch/read the source
  2. Extract fields into fixtures/vendor_catalogs/<vendor>.yaml
  3. Scaffold ontology/<vendor>_dialect.yaml
  4. Display both as tables for review
"""
import pathlib
import re
import subprocess
import sys

import streamlit as st
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
CATALOG_DIR = ROOT / "fixtures" / "vendor_catalogs"
DIALECT_DIR = ROOT / "ontology"
DOCS_DIR = ROOT / "fixtures" / "vendor_docs"
PROPOSED_DIR = ROOT / "ontology" / "proposed"

st.set_page_config(page_title="Lexicon — Vendor Onboarding", layout="wide", page_icon="🔤")


# --------------------------------------------------------------------------
# Field extraction — handles Markdown docs (AWS-style ## Heading + `API_ID`)
# and CSV headers. HTML/PDF stripped to text first.
# --------------------------------------------------------------------------
def extract_fields_from_markdown(text: str) -> dict:
    """Find `## Heading` sections and pull out the SCREAMING_SNAKE_CASE API id inside."""
    fields = {}
    sections = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    for sec in sections:
        m_head = re.match(r"([^\n<]+)", sec)
        if not m_head:
            continue
        heading = m_head.group(1).strip()
        m_api = re.search(r"API metric identifier:\s*`([A-Z][A-Z0-9_]{2,})`", sec) \
             or re.search(r"API:\s*`([A-Z][A-Z0-9_]{2,})`", sec) \
             or re.search(r"`([A-Z][A-Z0-9_]{3,})`", sec)
        if not m_api:
            continue
        api = m_api.group(1)
        # First non-empty descriptive line
        desc = ""
        for line in sec.split("\n")[1:]:
            line = line.strip()
            if not line or line.startswith(("<a name=", "**", "+", "#")):
                continue
            desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
            desc = re.sub(r"`([^`]+)`", r"\1", desc)
            break
        m_sent = re.match(r"(.{0,180}?[.!?])(?:\s|$)", desc)
        if m_sent:
            desc = m_sent.group(1)
        fields[api] = f"{heading}: {desc.strip()}"[:250]
    return fields


def extract_fields_from_csv_header(text: str) -> dict:
    """First non-empty line = header row; treat each column as a field."""
    for line in text.splitlines():
        if line.strip():
            return {col.strip(): "" for col in line.split(",") if col.strip()}
    return {}


def strip_html(text: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def extract_fields(content: str, filename_hint: str = "") -> dict:
    """Dispatch by content shape."""
    lower = filename_hint.lower()
    if lower.endswith(".csv"):
        return extract_fields_from_csv_header(content)
    if lower.endswith((".html", ".htm")) or content.lstrip().startswith("<"):
        content = strip_html(content)
    # Try markdown-style first (works for AWS and many other doc sites' .md variant)
    fields = extract_fields_from_markdown(content)
    if fields:
        return fields
    # Fallback: any SCREAMING_SNAKE_CASE token in backticks
    return {m.group(1): "" for m in re.finditer(r"`([A-Z][A-Z0-9_]{3,})`", content)}


# --------------------------------------------------------------------------
# Fetch — uses curl (respects system trust store for corporate SSL proxies)
# --------------------------------------------------------------------------
def fetch_url(url: str, vendor_lower: str, log) -> tuple[str, str]:
    """Return (content, saved_filename). Tries .md variant of AWS docs first."""
    cache_dir = DOCS_DIR / vendor_lower
    cache_dir.mkdir(parents=True, exist_ok=True)

    candidates = []
    if url.endswith(".html"):
        candidates.append(url[:-5] + ".md")
    candidates.append(url)

    for try_url in candidates:
        suffix = pathlib.Path(re.sub(r"\?.*$", "", try_url)).suffix or ".txt"
        local = cache_dir / f"source{suffix}"
        r = subprocess.run(
            ["curl", "-sL", "-A", "Lexicon-UI/1.0", "-o", str(local), try_url],
            capture_output=True, timeout=45,
        )
        if r.returncode == 0 and local.exists() and local.stat().st_size > 200:
            log(f"Fetched {try_url} → {local.name} ({local.stat().st_size:,} bytes)")
            return local.read_text(errors="ignore"), local.name
        log(f"[skip] {try_url} — {'empty' if local.exists() else 'no file'}")
    raise RuntimeError("All fetch attempts failed. Corporate SSL/proxy may be blocking, or URL is wrong.")


# --------------------------------------------------------------------------
# Persist catalog + trigger scaffold
# --------------------------------------------------------------------------
def write_catalog(vendor: str, fields: dict, source_ref: str) -> pathlib.Path:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    catalog = {
        "meta": {
            "vendor": vendor,
            "source": [{"name": "user-provided", "ref": source_ref}],
        },
        "fields": fields,
    }
    path = CATALOG_DIR / f"{vendor.lower()}.yaml"
    path.write_text(
        "# Populated by src/ui/app.py from a user-provided source.\n"
        + yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True, width=140)
    )
    return path


def run_scaffold(vendor: str, catalog_path: pathlib.Path, log) -> pathlib.Path | None:
    r = subprocess.run(
        ["python3", str(ROOT / "src" / "scaffold_dialect.py"), vendor,
         "--catalog", str(catalog_path.relative_to(ROOT)), "--force"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    for line in (r.stdout + r.stderr).splitlines():
        if line.strip():
            log(line.strip())
    if r.returncode != 0:
        return None
    dialect_path = DIALECT_DIR / f"{vendor.lower()}_dialect.yaml"
    return dialect_path if dialect_path.exists() else None


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
for key, default in [
    ("catalog", None), ("dialect", None), ("logs", []),
    ("raw_preview", ""), ("last_vendor", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def log(msg: str):
    st.session_state.logs.append(msg)


def _find_by_prefix(directory: pathlib.Path, prefix: str, suffix: str) -> pathlib.Path | None:
    """First file matching <prefix>*<suffix> in directory (non-recursive)."""
    if not directory.exists():
        return None
    exact = directory / f"{prefix}{suffix}"
    if exact.exists():
        return exact
    for p in sorted(directory.glob(f"{prefix}*{suffix}")):
        if p.is_file():
            return p
    return None


def load_existing(vendor: str):
    """When user types a vendor name, auto-load existing files if any.

    Filenames on disk don't always follow <vendor>.yaml — e.g. Avaya's catalog
    is avaya_hsplit_fields.yaml and its dialect is avaya_cms_dialect.yaml.
    Fall back to a prefix glob so those load when the user types "Avaya".
    """
    if not vendor:
        return
    lv = vendor.lower()
    cp = _find_by_prefix(CATALOG_DIR, lv, ".yaml")
    dp = _find_by_prefix(DIALECT_DIR, lv, "_dialect.yaml")
    if cp:
        st.session_state.catalog = yaml.safe_load(cp.read_text())
        log(f"Loaded catalog: {cp.relative_to(ROOT)}")
    if dp:
        st.session_state.dialect = yaml.safe_load(dp.read_text())
        log(f"Loaded dialect: {dp.relative_to(ROOT)}")


# --------------------------------------------------------------------------
# Layout — sidebar inputs + main area tabs
# --------------------------------------------------------------------------
st.title("Lexicon — Vendor Onboarding UI")
st.caption(
    "Give a vendor documentation URL (or upload a file). "
    "Get a vendor catalog + a dialect stub ready for a human expert to fill in the traps."
)

with st.sidebar:
    st.header("1. Vendor")
    vendor = st.text_input("Name", placeholder="e.g. Cisco_UCCE, Five9, AmazonConnect",
                           key="vendor_input")

    st.divider()
    st.header("2. Source doc")
    src_mode = st.radio("Provide source as", ["URL", "Upload file"], horizontal=True)
    url = ""
    uploaded = None
    if src_mode == "URL":
        url = st.text_input(
            "Documentation URL",
            placeholder="https://docs.example.com/metrics-reference",
            help="Tip: for AWS docs, use the .html URL — the app auto-tries the .md variant which parses cleaner.",
        )
    else:
        uploaded = st.file_uploader(
            "Upload doc", type=["md", "html", "htm", "txt", "csv"],
            help="Markdown parses best. HTML gets tag-stripped. CSV treats the header row as field names.",
        )

    st.divider()
    run = st.button("Discover & Scaffold", type="primary",
                    disabled=not vendor or (src_mode == "URL" and not url) or (src_mode == "Upload file" and uploaded is None))

# Auto-load existing files when user types a vendor name that's already onboarded
if vendor and vendor != st.session_state.last_vendor:
    st.session_state.last_vendor = vendor
    st.session_state.catalog = None
    st.session_state.dialect = None
    load_existing(vendor)

# --------------------------------------------------------------------------
# Action
# --------------------------------------------------------------------------
if run:
    st.session_state.logs = []
    try:
        with st.spinner("Fetching + extracting…"):
            if url:
                content, saved_name = fetch_url(url, vendor.lower(), log)
                source_ref = url
            else:
                content = uploaded.read().decode(errors="ignore")
                saved_name = uploaded.name
                source_ref = uploaded.name
                log(f"Loaded uploaded file: {saved_name} ({len(content):,} chars)")

            fields = extract_fields(content, filename_hint=saved_name)
            log(f"Extracted {len(fields)} vendor field(s)")

            catalog_path = write_catalog(vendor, fields, source_ref)
            log(f"Wrote {catalog_path.relative_to(ROOT)}")
            st.session_state.catalog = yaml.safe_load(catalog_path.read_text())
            st.session_state.raw_preview = content[:8000]

            dialect_path = run_scaffold(vendor, catalog_path, log)
            if dialect_path:
                st.session_state.dialect = yaml.safe_load(dialect_path.read_text())
        st.success(f"Done. Onboarded '{vendor}' with {len(fields)} vendor field(s).")
    except Exception as e:  # noqa: BLE001
        st.error(f"Failed: {e}")
        log(f"ERROR: {e}")

# --------------------------------------------------------------------------
# Main area — tabs
# --------------------------------------------------------------------------
if not vendor:
    st.info("👈 Enter a vendor name in the sidebar to begin.")
    st.stop()

cat = st.session_state.catalog
dia = st.session_state.dialect

# Summary metrics strip
if cat or dia:
    c1, c2, c3, c4 = st.columns(4)
    field_count = len(cat.get("fields", {})) if cat else 0
    if dia:
        all_defs = [d for section in ("queue", "agent_queue", "agent_system")
                    for d in dia.get(section, {}).values() if isinstance(d, dict)]
        confirmed = sum(1 for d in all_defs if d.get("confirmed"))
        total_canonical = len(all_defs)
        watchlist = len(dia.get("drift_watchlist", {}).get("boundary_terms", []))
    else:
        confirmed = total_canonical = watchlist = 0
    c1.metric("Vendor fields", field_count)
    c2.metric("Canonical fields (stub)", total_canonical)
    c3.metric("Confirmed", f"{confirmed}/{total_canonical}" if total_canonical else "—")
    c4.metric("Watchlist boundary terms", watchlist)

tab_cat, tab_dialect, tab_raw, tab_logs = st.tabs(
    ["📇 Vendor Catalog", "📖 Dialect Stub", "📄 Raw Content", "📝 Logs"]
)

# --- Catalog tab ---
with tab_cat:
    if not cat:
        st.info("No catalog yet. Provide a source and click 'Discover & Scaffold'.")
    else:
        meta = cat.get("meta", {})
        with st.expander("Meta", expanded=False):
            st.json(meta)
        fields = cat.get("fields", {})
        if fields:
            rows = [{"Field": k, "Description": v} for k, v in fields.items()]
            st.dataframe(rows, use_container_width=True, height=560, hide_index=True)
            st.download_button(
                "⬇ Download catalog YAML",
                data=yaml.safe_dump(cat, sort_keys=False, allow_unicode=True),
                file_name=f"{vendor.lower()}.yaml",
                mime="text/yaml",
            )
        else:
            st.warning("Catalog has no fields. Extractor didn't recognize the doc shape — try uploading a markdown version.")

# --- Dialect tab ---
with tab_dialect:
    if not dia:
        st.info("No dialect yet. Provide a source and click 'Discover & Scaffold'.")
    else:
        vkey = vendor.lower()
        st.caption(
            "🟢 Confirmed  ·  ⚪ Not yet confirmed  ·  ⚠️ Trap present. "
            "This is the STUB. A human expert must fill in the `Vendor Term(s)`, `Rule`, and `Trap` "
            "columns and flip Confirmed to true after cross-checking the vendor's own schema doc."
        )
        for section in ("queue", "agent_queue", "agent_system"):
            if section not in dia:
                continue
            st.markdown(f"### `{section}`")
            rows = []
            for cname, cdef in dia[section].items():
                if not isinstance(cdef, dict):
                    continue
                vterms = cdef.get(vkey, [])
                if not isinstance(vterms, list):
                    vterms = [vterms] if vterms else []
                rows.append({
                    " ": "🟢" if cdef.get("confirmed") else "⚪",
                    "Canonical Field": cname,
                    "Vendor Term(s)": ", ".join(vterms) or "—",
                    "Rule": cdef.get("rule") or "—",
                    "Trap": ("⚠️ " + cdef["trap"]) if cdef.get("trap") else "",
                    "Confirmed": bool(cdef.get("confirmed")),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True,
                         column_config={"Confirmed": st.column_config.CheckboxColumn(disabled=True)})

        wl = dia.get("drift_watchlist", {})
        if wl:
            with st.expander(f"Drift watchlist  ·  {len(wl.get('boundary_terms', []))} boundary terms", expanded=False):
                fcol, bcol = st.columns(2)
                fcol.markdown("**Forbidden terms**")
                fcol.write(wl.get("forbidden_terms", []))
                bcol.markdown("**Boundary terms**")
                bcol.write(wl.get("boundary_terms", []))

        st.download_button(
            "⬇ Download dialect YAML",
            data=yaml.safe_dump(dia, sort_keys=False, allow_unicode=True),
            file_name=f"{vendor.lower()}_dialect.yaml",
            mime="text/yaml",
        )

# --- Raw preview ---
with tab_raw:
    if st.session_state.raw_preview:
        st.caption(f"First {len(st.session_state.raw_preview):,} chars of the fetched source.")
        st.text(st.session_state.raw_preview)
    else:
        st.info("Raw source appears here after a Discover run.")

# --- Logs ---
with tab_logs:
    if st.session_state.logs:
        for msg in st.session_state.logs:
            st.text(msg)
    else:
        st.info("Action logs appear here.")
