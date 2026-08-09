"""Loader for ontology/registry/*.yaml. Validates every entry against the
VendorRegistryEntry dataclass and raises RegistryError on malformed entries.
"""
from __future__ import annotations
from pathlib import Path
import yaml

from .models import RegistryAccess, RegistrySource, VendorRegistryEntry
from .validation import validate_slug

VALID_CATEGORIES = {"fixed_schema", "flow_configured"}
VALID_SOURCE_KINDS = {"html_doc", "openapi", "graphql", "wsdl"}
VALID_ACCESS_METHODS = {
    "rest_api", "soap_api", "graphql_api",
    "file_export", "database_direct", "webhook_push", "streaming",
}
VALID_AUTH_METHODS = {
    "api_key", "oauth2_client_credentials", "oauth2_authorization_code",
    "basic_auth", "bearer_token", "session_token",
    "mtls", "aws_signature_v4", "iam_role", "sso_saml", "sshkey",
}


class RegistryError(ValueError):
    pass


def _load_one(path: Path) -> VendorRegistryEntry:
    raw = yaml.safe_load(path.read_text()) or {}
    for req in ("slug", "name", "category", "description", "sources"):
        if req not in raw:
            raise RegistryError(f"{path.name}: missing required key {req!r}")
    try:
        validate_slug(raw["slug"], f"{path.name}")
    except ValueError as exc:
        raise RegistryError(str(exc)) from exc
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
    access = []
    for i, a in enumerate(raw.get("access") or []):
        method = a.get("method")
        if method not in VALID_ACCESS_METHODS:
            raise RegistryError(
                f"{path.name}: access[{i}].method={method!r} not in {sorted(VALID_ACCESS_METHODS)}"
            )
        auth = tuple(a.get("auth") or ())
        for auth_m in auth:
            if auth_m not in VALID_AUTH_METHODS:
                raise RegistryError(
                    f"{path.name}: access[{i}].auth contains {auth_m!r}; "
                    f"must be one of {sorted(VALID_AUTH_METHODS)}"
                )
        access.append(RegistryAccess(
            method=method,
            description=a.get("description", ""),
            endpoint=a.get("endpoint"),
            format=a.get("format"),
            auth=auth,
            docs=a.get("docs"),
            notes=a.get("notes", ""),
        ))

    return VendorRegistryEntry(
        slug=raw["slug"],
        name=raw["name"],
        aliases=raw.get("aliases", []),
        category=raw["category"],
        description=raw["description"],
        sources=sources,
        access=access,
        version=raw.get("version", {}),
    )


def load_registry(dir_: Path) -> list[VendorRegistryEntry]:
    if not dir_.exists():
        return []
    return [_load_one(p) for p in sorted(dir_.glob("*.yaml"))]
