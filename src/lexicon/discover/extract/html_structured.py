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


IDENT_RE = re.compile(r"^[A-Za-z_][\w.]{0,60}$")
FIELD_HEADERS = {"field", "name", "column", "attribute", "property", "key"}
DESC_HEADERS = {"description", "definition", "meaning", "notes", "summary", "desc"}


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
