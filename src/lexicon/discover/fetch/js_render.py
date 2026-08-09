"""Headless-browser fetch for JavaScript-rendered documentation sites.

Many modern vendor documentation portals (community sites, Zoomin-powered
docs, developer portals built on Docusaurus/Nextra/etc.) are single-page
apps whose content is populated by JavaScript after the initial HTML shell
loads. Fetching them with a plain HTTP client (like httpx) returns only
the shell — usually a few hundred bytes of "enable JavaScript" placeholder.

This module fetches such pages via Playwright's headless Chromium, waits
for the JavaScript to render the DOM, and returns the resulting HTML.

Playwright is an OPTIONAL dependency. If it isn't installed, this module's
`is_available()` returns False and callers can skip the JS-rendering path.
"""
from __future__ import annotations
import re
from typing import Optional

# --- JS-shell detection ------------------------------------------------------

_JS_SHELL_MARKERS = (
    "you need to enable javascript",
    "please enable javascript",
    'id="root"',
    'id="__next"',
    "data-reactroot",
    "ng-app",
)


def looks_like_js_shell(html: str, visible_text_len_threshold: int = 800) -> bool:
    """Heuristic: does this HTML look like an unrendered SPA shell?

    Returns True if:
      - the visible-text length is below `visible_text_len_threshold`, AND
      - a known SPA marker or "enable JavaScript" phrase is present in the raw HTML.

    Deliberately conservative: false negatives are fine (regular HTML pages
    won't trigger JS re-fetch); false positives (real content misidentified
    as JS shell) would just cause an unnecessary re-fetch.
    """
    lower = html.lower()
    has_marker = any(m in lower for m in _JS_SHELL_MARKERS)
    if not has_marker:
        return False
    # Cheap visible-text estimate: strip tags + collapse whitespace.
    stripped = re.sub(r"<script[^>]*>.*?</script>", " ", lower, flags=re.DOTALL)
    stripped = re.sub(r"<style[^>]*>.*?</style>",   " ", stripped, flags=re.DOTALL)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    visible = re.sub(r"\s+", " ", stripped).strip()
    return len(visible) < visible_text_len_threshold


# --- Playwright fetch --------------------------------------------------------

def is_available() -> bool:
    """Is Playwright installed and importable in this environment?"""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def fetch_rendered_html(url: str, timeout_ms: int = 20_000) -> Optional[str]:
    """Fetch `url` in a headless Chromium and return the post-JS DOM HTML.

    Returns None if Playwright isn't installed (callers should fall back).
    Raises RuntimeError on browser-side failures — those are unrecoverable
    for this URL and the caller should mark the source as errored.

    Uses `wait_until="networkidle"` so single-page apps have time to fetch
    and render their content-panel data before we snapshot the DOM.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                           "Version/17.0 Safari/605.1.15",
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except PWTimeout:
                # Not fatal — the page may have loaded enough content anyway.
                # Wait a little more for late-arriving XHRs then snapshot.
                page.wait_for_timeout(2000)
            html = page.content()
            return html
        finally:
            browser.close()
