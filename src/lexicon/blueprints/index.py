"""Discover blueprint files on disk.

A blueprint file is a `.md` file with YAML frontmatter that contains a
`platform:` key. Files without frontmatter (e.g., README.md) are skipped.
"""
from __future__ import annotations
from pathlib import Path


def discover(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    out: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        try:
            head = "".join(path.open("r").readlines()[:20])
        except OSError:
            continue
        stripped = head.lstrip("\n")
        if stripped.startswith("---") and "\nplatform:" in stripped:
            out.append(path)
    return out
