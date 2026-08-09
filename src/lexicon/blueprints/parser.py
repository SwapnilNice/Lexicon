"""Parse a blueprint.md file into a ParsedBlueprint.

Frontmatter is a YAML block between --- markers at the top of the file.
Sections are `# Section Name` lines followed by their body.
Event subsections are `### <event.name>` lines inside "ACD event mapping"
with bullet items formatted as `- **<Micro-field>:** <value>`.

Code fences (``` ... ```) are respected — `#` inside a code fence is not a
section header.
"""
from __future__ import annotations
from pathlib import Path
import re

import yaml

from .models import ParsedBlueprint


class ParserError(ValueError):
    pass


_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.DOTALL)
_SECTION_HEADER_RE = re.compile(r"^# (.+)$")
_EVENT_HEADER_RE = re.compile(r"^### (.+)$")
_MICRO_FIELD_RE = re.compile(r"^- \*\*(.+?):\*\*\s+(.+)$")
_CODE_FENCE_RE = re.compile(r"^```")


def parse_blueprint(path: Path) -> ParsedBlueprint:
    text = Path(path).read_text()
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ParserError(f"{path.name}: missing frontmatter (expected --- ... --- at top)")
    fm_text, body = m.group(1), m.group(2)
    try:
        frontmatter = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise ParserError(f"{path.name}: malformed YAML frontmatter: {e}")

    sections: list[tuple[str, str]] = []
    event_subsections: dict[str, dict[str, str]] = {}

    current_section: str | None = None
    current_section_lines: list[str] = []
    current_event: str | None = None
    in_code_fence = False

    def flush_section():
        if current_section is not None:
            sections.append((current_section, "\n".join(current_section_lines)))

    for line in body.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_code_fence = not in_code_fence
            current_section_lines.append(line)
            continue
        if in_code_fence:
            current_section_lines.append(line)
            continue

        h = _SECTION_HEADER_RE.match(line)
        if h:
            flush_section()
            current_section = h.group(1).strip()
            current_section_lines = []
            current_event = None
            continue

        eh = _EVENT_HEADER_RE.match(line)
        if eh and current_section == "ACD event mapping":
            current_event = eh.group(1).strip()
            event_subsections[current_event] = {}
            current_section_lines.append(line)
            continue

        if current_event is not None:
            mm = _MICRO_FIELD_RE.match(line)
            if mm:
                event_subsections[current_event][mm.group(1).strip()] = mm.group(2).strip()
            current_section_lines.append(line)
            continue

        current_section_lines.append(line)

    flush_section()

    return ParsedBlueprint(
        path=Path(path),
        frontmatter=frontmatter,
        sections=sections,
        event_subsections=event_subsections,
    )
