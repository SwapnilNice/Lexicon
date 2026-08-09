"""Lexicon — Discovery Pipeline (v1) — Streamlit page.

Drives `python -m lexicon.discover` end-to-end from a browser.

Run from the repo root:
    streamlit run src/ui/app.py
Then click "Discovery Pipeline" in the sidebar.

What this page does:
    1. User enters a vendor slug or name (e.g. "avaya_cms", "Five9", "Genesys Cloud").
    2. Optionally: offline mode (cache-only, zero network / zero LLM calls).
    3. Pipeline runs: resolve → fetch → extract → enrich → map → report.
    4. Displays: coverage report, proposed mapping, rich catalog, registry entry.
    5. Download buttons for each artifact.

The page invokes the pipeline in-process (no subprocess), so it inherits the
Python virtualenv and Streamlit's error surface. Errors are shown inline with
a full traceback so a user can diagnose without dropping to the terminal.
"""
from __future__ import annotations
import sys
from pathlib import Path
import subprocess

import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Import the pipeline modules AFTER sys.path setup.
from lexicon.discover.cache import DiskCache        # noqa: E402
from lexicon.discover.llm import LLMClient          # noqa: E402
from lexicon.discover.pipeline import run_pipeline  # noqa: E402
from lexicon.discover.registry import load_registry # noqa: E402
from lexicon.discover.resolver import (             # noqa: E402
    resolve_vendor_with_fallback, ResolveError,
)


st.set_page_config(
    page_title="Lexicon — Discovery Pipeline",
    layout="wide",
    page_icon="🔎",
)

REGISTRY_DIR   = ROOT / "ontology" / "registry"
CATALOGS_DIR   = ROOT / "fixtures" / "vendor_catalogs"
PROPOSED_DIR   = ROOT / "ontology" / "proposed"
REPORTS_DIR    = ROOT / "out" / "discovery_reports"
CACHE_DIR      = ROOT / "state" / "discovery_cache"
BLUEPRINTS_DIR = ROOT / "ontology" / "blueprints"


# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
for key, default in [
    ("last_run", None),
    ("last_error", None),
]:
    st.session_state.setdefault(key, default)


# ---------------------------------------------------------------------------
# Registry helpers — for the "known vendors" quick-pick list
# ---------------------------------------------------------------------------
def _known_vendors() -> list[tuple[str, str]]:
    """Return [(slug, display_name), ...] for the sidebar quick-pick."""
    try:
        entries = load_registry(REGISTRY_DIR)
    except Exception:  # noqa: BLE001
        return []
    return sorted((e.slug, e.name) for e in entries)


# ---------------------------------------------------------------------------
# Layout — sidebar inputs
# ---------------------------------------------------------------------------
st.title("🔎 Discovery Pipeline (v1)")
st.caption(
    "Give a vendor slug or name → Lexicon fetches its docs, extracts fields, "
    "infers units + semantic tags, and proposes a canonical mapping. "
    "See `docs/superpowers/specs/2026-08-09-discovery-deepening-design.md`."
)

with st.sidebar:
    st.header("1. Vendor")

    known = _known_vendors()
    if known:
        with st.expander(f"📚 Known vendors ({len(known)})", expanded=False):
            for slug, name in known:
                st.text(f"  {slug:20} — {name}")

    vendor = st.text_input(
        "Vendor slug or name",
        placeholder="e.g. avaya_cms, five9, Genesys Cloud",
        help="If unknown, the pipeline falls back to LLM-suggested doc URLs "
             "(needs ANTHROPIC_API_KEY unless offline).",
    )

    st.divider()
    st.header("2. Options")
    offline = st.checkbox(
        "Offline mode",
        value=True,
        help="No network / no LLM calls. Reads only from the on-disk cache. "
             "Safe default for repeated runs.",
    )
    report = st.selectbox(
        "Report type",
        ["queue", "agentqueue", "agentsystem"],
        help="Which WFM interval report to target.",
    )

    st.divider()
    run = st.button(
        "Run Discovery",
        type="primary",
        disabled=not vendor,
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------
if run:
    st.session_state.last_error = None
    st.session_state.last_run = None
    st.session_state.pop("flow_configured", None)
    with st.spinner(f"Resolving `{vendor}`…"):
        try:
            cache = DiskCache(CACHE_DIR, offline=offline)
            llm = LLMClient(cache=cache, offline=offline)
            entries = load_registry(REGISTRY_DIR)
            resolve = resolve_vendor_with_fallback(vendor, entries, llm)
        except ResolveError as e:
            st.session_state.last_error = f"Vendor resolution failed: {e}"
            resolve = None
        except Exception as e:  # noqa: BLE001
            import traceback
            st.session_state.last_error = (
                f"Resolve failed: {e}\n\n"
                f"```\n{traceback.format_exc()}\n```"
            )
            resolve = None

    # ----------------------------------------------------------------------
    # Route by vendor category. Fixed-schema vendors run through the
    # extraction pipeline (sub-project A). Flow-configured platforms
    # (Salesforce, Dynamics 365, ServiceNow CX, …) are NOT extractable —
    # their data model is emergent from admin configuration. Route those
    # to their Flow Blueprint(s) instead of running an extractor that
    # will always return 0/N.
    # ----------------------------------------------------------------------
    if resolve is not None and resolve.entry.category == "flow_configured":
        blueprints = sorted((BLUEPRINTS_DIR / resolve.entry.slug).glob("*.md"))
        st.session_state.flow_configured = {
            "slug": resolve.entry.slug,
            "name": resolve.entry.name,
            "description": resolve.entry.description,
            "blueprint_paths": [str(p) for p in blueprints],
        }
    elif resolve is not None:
        with st.spinner(f"Running discovery pipeline for `{resolve.entry.slug}`…"):
            try:
                r = run_pipeline(
                    entry=resolve.entry, cache=cache, llm=llm,
                    catalogs_dir=CATALOGS_DIR,
                    proposed_dir=PROPOSED_DIR,
                    reports_dir=REPORTS_DIR,
                    report=report,
                )
                st.session_state.last_run = {
                    "slug": resolve.entry.slug,
                    "resolved_via": resolve.resolved_via,
                    "report": report,
                    "n_found": r.n_found,
                    "n_fields": r.n_fields,
                    "catalog_path": str(r.catalog_path),
                    "proposed_path": str(r.proposed_path),
                    "report_path":  str(r.report_path),
                }
            except Exception as e:  # noqa: BLE001
                import traceback
                st.session_state.last_error = (
                    f"Pipeline failed: {e}\n\n"
                    f"```\n{traceback.format_exc()}\n```"
                )

# ---------------------------------------------------------------------------
# Result display
# ---------------------------------------------------------------------------
if st.session_state.last_error:
    st.error(st.session_state.last_error)

# ----- Flow-configured routing -----
fc = st.session_state.get("flow_configured")
if fc:
    st.info(
        f"**`{fc['slug']}` is a flow-configured platform.** The extraction "
        f"pipeline (sub-project A) is not the right tool here — flow-configured "
        f"platforms don't have a fixed schema you can crawl. Their ACD data "
        f"footprint is emergent from admin configuration. Use the "
        f"**Flow Blueprint** capability instead."
    )
    st.caption(fc["description"])

    blueprint_paths = [Path(p) for p in fc["blueprint_paths"]]
    if not blueprint_paths:
        st.warning(
            f"No blueprints found under `ontology/blueprints/{fc['slug']}/`. "
            f"Author one following the framework at "
            f"`docs/superpowers/specs/2026-08-09-flow-blueprint-design.md`."
        )
    else:
        st.subheader(f"Available blueprints for {fc['name']}")
        # One tab per blueprint — routing-model as the tab label
        tabs = st.tabs([p.stem for p in blueprint_paths])
        for tab, path in zip(tabs, blueprint_paths):
            with tab:
                content = path.read_text()
                st.markdown(f"**Source:** `{path.relative_to(ROOT)}`")
                # Split frontmatter from body so YAML doesn't render as prose
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        with st.expander("YAML frontmatter", expanded=False):
                            st.code(parts[1].strip(), language="yaml")
                        body = parts[2].lstrip()
                    else:
                        body = content
                else:
                    body = content
                st.markdown(body)
                st.download_button(
                    "⬇ Download blueprint",
                    data=content,
                    file_name=path.name,
                    mime="text/markdown",
                    key=f"dl_{path.stem}",
                )
    st.stop()

last = st.session_state.last_run

if not last:
    st.info("👈 Enter a vendor and click **Run Discovery** to begin.")
    if not offline:
        st.stop()
    # Even without a run, show something useful — list of known vendors as clickable hints
    st.subheader("Known vendors in the registry")
    if not known:
        st.text("(no vendors registered yet)")
    else:
        rows = []
        for slug, name in known:
            catalog = CATALOGS_DIR / f"{slug}.yaml"
            proposed = PROPOSED_DIR / f"{slug}.queue.PROPOSED.yaml"
            report_file = REPORTS_DIR / f"{slug}.md"
            rows.append({
                "Slug": slug,
                "Name": name,
                "Catalog": "✓" if catalog.exists() else "—",
                "Proposed": "✓" if proposed.exists() else "—",
                "Report": "✓" if report_file.exists() else "—",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    st.stop()

# We have a result.
n_found = last["n_found"]
n_fields = last["n_fields"]
success_rate = (n_found / n_fields * 100) if n_fields else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Vendor slug", last["slug"])
c2.metric("Resolved via", last["resolved_via"])
c3.metric("Fields found", f"{n_found}/{n_fields}")
c4.metric("Coverage", f"{success_rate:.0f}%")

tab_report, tab_proposed, tab_catalog, tab_registry = st.tabs(
    ["📋 Coverage Report", "🗺 Proposed Mapping", "📇 Rich Catalog", "🌳 Registry Entry"]
)

# --- Coverage Report ---
with tab_report:
    report_path = Path(last["report_path"])
    if report_path.exists():
        st.markdown(report_path.read_text())
        st.download_button(
            "⬇ Download report (.md)",
            data=report_path.read_text(),
            file_name=report_path.name,
            mime="text/markdown",
        )
    else:
        st.warning(f"Report file not found: {report_path}")

# --- Proposed Mapping ---
with tab_proposed:
    proposed_path = Path(last["proposed_path"])
    if proposed_path.exists():
        text = proposed_path.read_text()
        try:
            doc = yaml.safe_load(text)
            fields = doc.get("fields", {})
            proposals = doc.get("proposals", {})
            if fields:
                rows = []
                for cname, formula in fields.items():
                    p = proposals.get(cname, {})
                    rows.append({
                        "Canonical Field": cname,
                        "Proposed Formula": formula,
                        "Confidence": p.get("confidence", "—"),
                        "Needs Review": "⚠️" if p.get("needs_review") else "",
                        "Rationale": p.get("rationale", "")[:120],
                    })
                st.dataframe(rows, use_container_width=True, hide_index=True, height=420)
            else:
                st.info("No proposed formulas — the mapper couldn't find candidates. Check the coverage report.")
            with st.expander("Full YAML", expanded=False):
                st.code(text, language="yaml")
        except yaml.YAMLError:
            st.code(text, language="yaml")
        st.download_button(
            "⬇ Download PROPOSED.yaml",
            data=text,
            file_name=proposed_path.name,
            mime="text/yaml",
        )
    else:
        st.warning(f"Proposed mapping file not found: {proposed_path}")

# --- Rich Catalog ---
with tab_catalog:
    catalog_path = Path(last["catalog_path"])
    if catalog_path.exists():
        text = catalog_path.read_text()
        try:
            doc = yaml.safe_load(text)
            fields = doc.get("fields", {})
            if fields:
                rows = []
                for name, spec in fields.items():
                    if isinstance(spec, str):
                        rows.append({"Field": name, "Description": spec})
                    else:
                        tags = ", ".join(t.get("tag", "") for t in spec.get("semantic_tags", []))
                        traps = ", ".join(t.get("kind", "") for t in spec.get("traps", []))
                        rows.append({
                            "Field": name,
                            "Description": (spec.get("description") or "")[:100],
                            "Unit": spec.get("unit", ""),
                            "Confidence": spec.get("unit_confidence", ""),
                            "Semantic Tags": tags,
                            "Traps": traps,
                        })
                st.dataframe(rows, use_container_width=True, hide_index=True, height=420)
            else:
                st.info(
                    "Catalog is empty — no fields were extracted. Usually means the source "
                    "URLs returned no static field tables (JS-rendered / auth-gated content). "
                    "See the coverage report tab for source-fetch status."
                )
            with st.expander("Full YAML", expanded=False):
                st.code(text, language="yaml")
        except yaml.YAMLError:
            st.code(text, language="yaml")
        st.download_button(
            "⬇ Download catalog YAML",
            data=text,
            file_name=catalog_path.name,
            mime="text/yaml",
        )
    else:
        st.warning(f"Catalog file not found: {catalog_path}")

# --- Registry Entry ---
with tab_registry:
    registry_file = REGISTRY_DIR / f"{last['slug']}.yaml"
    if registry_file.exists():
        st.markdown(f"**Registry file:** `{registry_file.relative_to(ROOT)}`")
        st.code(registry_file.read_text(), language="yaml")
    else:
        st.info(
            f"No registry file for `{last['slug']}` — this vendor was resolved via "
            f"**{last['resolved_via']}** (typically LLM search fallback). "
            f"Consider committing a registry entry at "
            f"`ontology/registry/{last['slug']}.yaml` for deterministic future runs."
        )

st.divider()
st.caption(
    f"Artifacts written to: "
    f"`{Path(last['catalog_path']).relative_to(ROOT)}`, "
    f"`{Path(last['proposed_path']).relative_to(ROOT)}`, "
    f"`{Path(last['report_path']).relative_to(ROOT)}`. "
    f"Next step: `python src/verify_mapping.py <proposed> <sample.csv> <golden.xml>`."
)
