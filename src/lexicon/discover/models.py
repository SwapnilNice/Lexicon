"""Dataclasses used by the discovery pipeline. Frozen where possible.

These are the *interfaces* between stages. Every stage consumes and emits
one of these; no stage should invent its own shape.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Source-kind vocabulary.
#
# There are TWO Literal aliases for source types, describing different levels
# of the pipeline. They map one-to-one but use different identifiers on
# purpose:
#
#   Fetcher input (RegistrySource.kind)   Extractor input (SourceDoc.kind)
#   ---------------------------------     ------------------------------
#   html_doc  (a documentation site)  →   html            (a fetched HTML page)
#                                     →   markdown        (fetched content that looks
#                                                          like Markdown, not HTML —
#                                                          e.g. AWS's .md variants)
#   openapi   (an OpenAPI spec URL)   →   openapi_schema  (one schema object)
#   graphql   (a GraphQL endpoint)    →   graphql_type    (one named type)
#   wsdl      (a WSDL URL)            →   wsdl_type       (one named type)
#
# Fetch strategies own this translation. Extractors dispatch on SourceDoc.kind.
# ---------------------------------------------------------------------------
SourceKind = Literal[
    "html", "markdown", "openapi_schema", "graphql_type", "wsdl_type",
]


@dataclass(frozen=True)
class FieldSource:
    """Where in the world a field mention was found."""
    doc_id: str
    url: str
    locator: str        # CSS selector for HTML; JSON pointer for schemas
    snippet: str        # short excerpt of the source content


@dataclass(frozen=True)
class SourceDoc:
    """One normalized source document. The uniform seam between fetch and extract."""
    id: str
    kind: SourceKind
    url: str
    title: str
    content: str        # raw payload — HTML text, or JSON schema as string, etc.
    text: str = ""      # cleaned plain text (HTML only); empty for schema docs


@dataclass(frozen=True)
class RawField:
    """A single vendor field mention extracted from one source."""
    name: str
    description: str
    source: FieldSource
    extractor: str      # html_structured | html_prose | openapi | graphql | wsdl
    confidence_extraction: float


@dataclass(frozen=True)
class SemanticTag:
    tag: str            # e.g. talk_time_like, hold_time_like, ready_time_like
    weight: float
    rationale: str = ""


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class RegistrySource:
    kind: Literal["html_doc", "openapi", "graphql", "wsdl"]
    role: Literal["primary", "secondary"]
    url: str | None
    crawl: dict[str, Any] = field(default_factory=dict)


# --- Data-access schema ------------------------------------------------------
# Runtime concerns: given a vendor, how does an integration engineer actually
# FETCH the historical / real-time data? What auth mechanisms are supported?
# The `sources` block above is for DOCUMENTATION discovery; this block is for
# the customer's production integration.

AccessMethod = Literal[
    "rest_api",           # HTTPS + JSON (most modern ACDs)
    "soap_api",           # SOAP + XML with WSDL
    "graphql_api",        # GraphQL endpoint
    "file_export",        # scheduled CSV/JSON export, typically SFTP or S3
    "database_direct",    # direct JDBC/ODBC read (older on-prem systems)
    "webhook_push",       # vendor pushes events to our endpoint
    "streaming",          # WebSocket / server-sent events
]

AuthMethod = Literal[
    "api_key",                     # simple header / query param
    "oauth2_client_credentials",   # machine-to-machine OAuth2
    "oauth2_authorization_code",   # user-consent OAuth2
    "basic_auth",                  # HTTP Basic username/password
    "bearer_token",                # opaque bearer (often issued by a login endpoint)
    "session_token",               # vendor-specific login → session cookie/token
    "mtls",                        # mutual TLS with client certs
    "aws_signature_v4",            # AWS SigV4 (for AWS-native vendors)
    "iam_role",                    # AWS IAM role assumption
    "sso_saml",                    # SAML-based SSO
    "sshkey",                      # SSH key (for SFTP-based file exports)
]


@dataclass(frozen=True)
class RegistryAccess:
    """One way to reach a vendor's data at runtime."""
    method: AccessMethod
    description: str = ""
    endpoint: str | None = None       # base URL or connection pattern
    format: str | None = None         # json | xml | csv | soap_envelope
    auth: tuple[AuthMethod, ...] = ()
    docs: str | None = None           # vendor docs page for this method
    notes: str = ""


@dataclass
class VendorRegistryEntry:
    slug: str
    name: str
    aliases: list[str]
    category: Literal["fixed_schema", "flow_configured"]
    description: str
    sources: list[RegistrySource]
    access: list[RegistryAccess] = field(default_factory=list)
    version: dict[str, Any] = field(default_factory=dict)
