"""Dataclasses used by the discovery pipeline. Frozen where possible.

These are the *interfaces* between stages. Every stage consumes and emits
one of these; no stage should invent its own shape.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal


SourceKind = Literal[
    "html", "openapi_schema", "graphql_type", "wsdl_type",
]


@dataclass
class FieldSource:
    """Where in the world a field mention was found."""
    doc_id: str
    url: str
    locator: str        # CSS selector for HTML; JSON pointer for schemas
    snippet: str        # short excerpt of the source content


@dataclass
class SourceDoc:
    """One normalized source document. The uniform seam between fetch and extract."""
    id: str
    kind: SourceKind
    url: str
    title: str
    content: str        # raw payload — HTML text, or JSON schema as string, etc.
    text: str = ""      # cleaned plain text (HTML only); empty for schema docs


@dataclass
class RawField:
    """A single vendor field mention extracted from one source."""
    name: str
    description: str
    source: FieldSource
    extractor: str      # html_structured | html_prose | openapi | graphql | wsdl
    confidence_extraction: float


@dataclass
class SemanticTag:
    tag: str            # e.g. talk_time_like, hold_time_like, ready_time_like
    weight: float
    rationale: str = ""


@dataclass
class Trap:
    kind: Literal["exclusion", "inclusion", "unit_slip"]
    target: str = ""    # e.g. hold_time
    evidence: str = ""  # short quote from the source


@dataclass
class EnrichedField:
    """A merged, unit-inferred, semantically-tagged vendor field."""
    name: str
    description: str
    sources: list[FieldSource]
    unit: str = "unknown"       # duration_seconds | count | percentage | key | unknown
    unit_confidence: float = 0.0
    unit_signals: list[str] = field(default_factory=list)
    semantic_tags: list[SemanticTag] = field(default_factory=list)
    traps: list[Trap] = field(default_factory=list)


@dataclass
class ProposedField:
    """One canonical field's proposed mapping (an arithmetic formula over vendor fields)."""
    formula: str | None
    confidence: float
    rationale: str
    alternates: list[dict[str, Any]] = field(default_factory=list)
    needs_review: bool = False


@dataclass
class RegistrySource:
    kind: Literal["html_doc", "openapi", "graphql", "wsdl"]
    role: Literal["primary", "secondary"]
    url: str | None
    crawl: dict[str, Any] = field(default_factory=dict)


@dataclass
class VendorRegistryEntry:
    slug: str
    name: str
    aliases: list[str]
    category: Literal["fixed_schema", "flow_configured"]
    description: str
    sources: list[RegistrySource]
    version: dict[str, Any] = field(default_factory=dict)
