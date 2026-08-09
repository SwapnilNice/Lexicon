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
    lines.append("| Canonical concept | Status | Proposed | Confidence | Rationale |")
    lines.append("|---|---|---|---|---|")
    found = 0
    for name, p in proposals.items():
        if p.formula is not None:
            found += 1
        status = _fmt_status(p)
        formula = p.formula or "(none)"
        lines.append(f"| {name} | {status} | `{formula}` | {p.confidence:.2f} | {p.rationale} |")
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
