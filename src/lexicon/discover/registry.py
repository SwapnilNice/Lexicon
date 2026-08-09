"""Loader for ontology/registry/*.yaml. Validates every entry against the
VendorRegistryEntry dataclass and raises RegistryError on malformed entries.
"""
from __future__ import annotations
from pathlib import Path
import yaml

from .models import RegistrySource, VendorRegistryEntry

VALID_CATEGORIES = {"fixed_schema", "flow_configured"}
VALID_SOURCE_KINDS = {"html_doc", "openapi", "graphql", "wsdl"}


class RegistryError(ValueError):
    pass


def _load_one(path: Path) -> VendorRegistryEntry:
    raw = yaml.safe_load(path.read_text()) or {}
    for req in ("slug", "name", "category", "description", "sources"):
        if req not in raw:
            raise RegistryError(f"{path.name}: missing required key {req!r}")
    if raw["category"] not in VALID_CATEGORIES:
        raise RegistryError(
            f"{path.name}: category={raw['category']!r} not in {sorted(VALID_CATEGORIES)}"
        )
    sources = []
    for i, s in enumerate(raw["sources"]):
        if s.get("kind") not in VALID_SOURCE_KINDS:
            raise RegistryError(
                f"{path.name}: sources[{i}].kind={s.get('kind')!r} not in {sorted(VALID_SOURCE_KINDS)}"
            )
        sources.append(
            RegistrySource(
                kind=s["kind"],
                role=s.get("role", "primary"),
                url=s.get("url"),
                crawl=s.get("crawl", {}),
            )
        )
    return VendorRegistryEntry(
        slug=raw["slug"],
        name=raw["name"],
        aliases=raw.get("aliases", []),
        category=raw["category"],
        description=raw["description"],
        sources=sources,
        version=raw.get("version", {}),
    )


def load_registry(dir_: Path) -> list[VendorRegistryEntry]:
    if not dir_.exists():
        return []
    return [_load_one(p) for p in sorted(dir_.glob("*.yaml"))]
