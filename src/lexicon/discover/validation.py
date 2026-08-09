"""Shared input validation. Slug validation prevents path traversal
from adversarial LLM outputs and malformed registry files."""
import re

_SAFE_SLUG_RE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


def validate_slug(slug: str, context: str) -> None:
    """Raise ValueError if the slug is unsafe for use as a filename component."""
    if not _SAFE_SLUG_RE.match(slug):
        raise ValueError(
            f"{context}: unsafe slug {slug!r}; expected pattern [a-z][a-z0-9_]{{0,63}}"
        )
