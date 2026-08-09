# Lexicon — Vendor Onboarding UI

A minimal Streamlit UI that wraps `discover.py` + `scaffold_dialect.py`.
Give it a vendor name + a URL (or upload a doc). It produces:
- `fixtures/vendor_catalogs/<vendor>.yaml` — the vendor field inventory
- `ontology/<vendor>_dialect.yaml` — the dialect stub, ready for expert fill-in

## Requirements

```bash
pip install streamlit pyyaml
```

## Run

From the project root:

```bash
streamlit run src/ui/app.py
```

Streamlit will open `http://localhost:8501` in your browser.

## Usage

1. **Sidebar → Vendor name** (e.g. `Cisco_UCCE`).
2. **Sidebar → Source doc**:
   - **URL** — for AWS-style docs, use the `.html` URL; the UI auto-tries the `.md` variant which parses cleaner.
   - **Upload file** — Markdown / HTML / text / CSV (CSVs use the header row as field names).
3. Click **Discover & Scaffold**.
4. Review the tabs:
   - **📇 Vendor Catalog** — every field the extractor found, in a searchable table.
   - **📖 Dialect Stub** — canonical fields with empty rows for vendor terms + traps.
   - **📄 Raw Content** — first 8 KB of what was fetched (for troubleshooting).
   - **📝 Logs** — action log.

If you re-open the UI later and type the same vendor name, it auto-loads the existing files — you don't have to re-fetch.

## Notes on the URL fetch

The UI uses `curl` under the hood (not Python's `urllib`) so it respects the system trust store — this matters on corporate networks with SSL-inspecting proxies where Python-level HTTPS fails.

If a URL still fails, either:
- The vendor blocks bot traffic (try a different UA, or download manually and use the upload path)
- The content is fully JS-rendered (no static HTML to parse — download the rendered HTML from your browser and upload it)

## What the UI does NOT do

- **It does not fill in the dialect for you.** That's the human expert's job — see `docs/DIALECT_AUTHORING.md`.
- **It does not run automap or verify.** For that, still use `./add_vendor.sh` or the individual scripts. This UI is for the discovery + scaffold steps only.
