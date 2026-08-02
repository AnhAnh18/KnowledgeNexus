"""Pure M7 trusted-input validation and Confluence crawl fingerprinting."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit

from knowledgenexus.foundation.domain.models.confluence_source_config import (
    ConfluenceExcludeSubtree,
    ConfluenceIncludeRoot,
    ConfluenceSourceConfig,
)


_PROFILE_KEYS = (
    "profile_id",
    "profile_version",
    "inventory_page_size",
    "attachment_page_size",
    "minimum_request_interval_seconds",
    "max_response_bytes_per_request",
    "max_total_requests_per_run",
    "max_attempts",
    "base_backoff_seconds",
    "max_retry_delay_seconds",
    "max_total_retry_delay_seconds",
    "jitter",
    "max_include_roots",
    "max_pages_per_run",
    "max_inventory_windows_per_root",
    "max_inventory_windows_per_run",
    "max_restriction_targets_per_page",
    "max_restriction_observations_per_run",
    "max_attachment_windows_per_page",
    "max_attachment_windows_per_run",
    "max_raw_bytes_per_run",
    "max_raw_artifacts_per_run",
    "minimum_free_disk_reserve_bytes",
)
_PROFILE_KEY_SET = frozenset(_PROFILE_KEYS)
_PROFILE_STRING_KEYS = ("profile_id", "profile_version")
_PROFILE_BOOL_KEYS = ("jitter",)
_PROFILE_FLOAT_KEYS = (
    "minimum_request_interval_seconds",
    "base_backoff_seconds",
    "max_retry_delay_seconds",
    "max_total_retry_delay_seconds",
)
_PROFILE_INT_KEYS = tuple(
    key
    for key in _PROFILE_KEYS
    if key not in _PROFILE_STRING_KEYS + _PROFILE_BOOL_KEYS + _PROFILE_FLOAT_KEYS
)

_APPROVED_PROFILES = (
    MappingProxyType(
        {
            "profile_id": "m7-crawl-reliability-v1",
            "profile_version": "1",
            "inventory_page_size": 50,
            "attachment_page_size": 50,
            "minimum_request_interval_seconds": 3.0,
            "max_response_bytes_per_request": 8388608,
            "max_total_requests_per_run": 50000,
            "max_attempts": 4,
            "base_backoff_seconds": 1.0,
            "max_retry_delay_seconds": 120.0,
            "max_total_retry_delay_seconds": 300.0,
            "jitter": False,
            "max_include_roots": 16,
            "max_pages_per_run": 10000,
            "max_inventory_windows_per_root": 1000,
            "max_inventory_windows_per_run": 4000,
            "max_restriction_targets_per_page": 256,
            "max_restriction_observations_per_run": 25000,
            "max_attachment_windows_per_page": 100,
            "max_attachment_windows_per_run": 10000,
            "max_raw_bytes_per_run": 34359738368,
            "max_raw_artifacts_per_run": 250000,
            "minimum_free_disk_reserve_bytes": 8589934592,
        }
    ),
    MappingProxyType(
        {
            "profile_id": "m7-crawl-scale-acceptance-v2",
            "profile_version": "2",
            "inventory_page_size": 50,
            "attachment_page_size": 50,
            "minimum_request_interval_seconds": 3.0,
            "max_response_bytes_per_request": 8388608,
            "max_total_requests_per_run": 50000,
            "max_attempts": 4,
            "base_backoff_seconds": 1.0,
            "max_retry_delay_seconds": 120.0,
            "max_total_retry_delay_seconds": 300.0,
            "jitter": False,
            "max_include_roots": 16,
            "max_pages_per_run": 100000,
            "max_inventory_windows_per_root": 2000,
            "max_inventory_windows_per_run": 4000,
            "max_restriction_targets_per_page": 256,
            "max_restriction_observations_per_run": 25000,
            "max_attachment_windows_per_page": 100,
            "max_attachment_windows_per_run": 10000,
            "max_raw_bytes_per_run": 34359738368,
            "max_raw_artifacts_per_run": 250000,
            "minimum_free_disk_reserve_bytes": 8589934592,
        }
    ),
)

_REGISTRY_CONSTANTS = MappingProxyType(
    {
        "fingerprint_contract_version": "m7-crawl-fingerprint-v1",
        "deployment_api_family": "confluence-data-center-rest-v1",
        "request_profile_version": "m7-confluence-request-profile-v1",
        "scope_policy_version": "m5-scope-policy-v1",
        "query_shape_profile_version": "m7-confluence-inventory-query-v1",
        "expand_shape_profile_version": "m7-confluence-inventory-expand-v1",
        "mapper_contract_version": "m5b-confluence-inventory-mapper-v1",
        "raw_layout_contract_version": "m7-raw-generation-layout-v1",
        "foundation_schema_version": "1.0",
        "chunking_contract_version": "1.2.0",
        "jira_relation_contract_version": "m6e-jira-relations-v1",
        "acl_contract_version": "m6f-acl-materialization-v1",
    }
)

_FINAL_PROFILE_INT_KEYS = (
    "inventory_page_size",
    "attachment_page_size",
    "max_include_roots",
    "max_pages_per_run",
    "max_inventory_windows_per_root",
    "max_inventory_windows_per_run",
    "max_restriction_targets_per_page",
    "max_restriction_observations_per_run",
    "max_attachment_windows_per_page",
    "max_attachment_windows_per_run",
    "max_total_requests_per_run",
    "max_response_bytes_per_request",
    "max_raw_bytes_per_run",
    "max_raw_artifacts_per_run",
    "minimum_free_disk_reserve_bytes",
)


@dataclass(frozen=True)
class _ValidatedSourceConfig:
    """Immutable M7 snapshot of the source fields used for fingerprinting."""

    space_key: str
    page_size: int
    include_roots: tuple[ConfluenceIncludeRoot, ...]
    exclude_subtrees: tuple[ConfluenceExcludeSubtree, ...]
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]


@dataclass(frozen=True, repr=False)
class _EffectiveCrawlInput:
    """One immutable effective-input snapshot for private coordination code."""

    fingerprint: ConfluenceCrawlFingerprint
    canonical_include_root_ids: tuple[str, ...]
    max_include_roots: int
    inventory_page_size: int
    max_pages_per_run: int
    max_inventory_windows_per_root: int
    max_inventory_windows_per_run: int

    def __repr__(self) -> str:
        return "_EffectiveCrawlInput()"


def _type_error() -> TypeError:
    return TypeError("invalid confluence crawl fingerprint input")


def _value_error() -> ValueError:
    return ValueError("invalid confluence crawl fingerprint input")


def _validate_profile(profile: object) -> Mapping[str, object]:
    if not isinstance(profile, Mapping):
        raise _type_error()
    try:
        # Snapshot untrusted Mapping implementations before validation and hashing.
        profile_snapshot = dict(profile)
        if frozenset(profile_snapshot.keys()) != _PROFILE_KEY_SET:
            raise _value_error()
        for key in _PROFILE_STRING_KEYS:
            if type(profile_snapshot[key]) is not str:
                raise _type_error()
        for key in _PROFILE_BOOL_KEYS:
            if type(profile_snapshot[key]) is not bool:
                raise _type_error()
        for key in _PROFILE_FLOAT_KEYS:
            value = profile_snapshot[key]
            if type(value) is not float:
                raise _type_error()
            if not math.isfinite(value):
                raise _value_error()
        for key in _PROFILE_INT_KEYS:
            if type(profile_snapshot[key]) is not int:
                raise _type_error()
        for key in _PROFILE_INT_KEYS + _PROFILE_FLOAT_KEYS:
            if profile_snapshot[key] <= 0:
                raise _value_error()
        for approved in _APPROVED_PROFILES:
            if all(profile_snapshot[key] == approved[key] for key in _PROFILE_KEYS):
                return profile_snapshot
    except (KeyError, TypeError, ValueError):
        raise _value_error() from None
    raise _value_error()


def _validate_source_config(source_config: object) -> _ValidatedSourceConfig:
    if not isinstance(source_config, ConfluenceSourceConfig):
        raise _type_error()
    try:
        # Read the caller object once. The returned snapshot is the only source
        # used after validation, even if a subclass exposes stateful attributes.
        source_id = source_config.source_id
        space_key = source_config.space_key
        page_size = source_config.page_size
        raw_include_roots = source_config.include_roots
        raw_exclude_subtrees = source_config.exclude_subtrees
        raw_include_keywords = source_config.include_keywords
        raw_exclude_keywords = source_config.exclude_keywords

        for value in (source_id, space_key):
            if type(value) is not str or not value:
                raise _value_error()
        if type(page_size) is not int or page_size <= 0:
            raise _value_error()
        if type(raw_include_roots) is not tuple or not raw_include_roots:
            raise _value_error()
        if type(raw_exclude_subtrees) is not tuple:
            raise _value_error()
        if type(raw_include_keywords) is not tuple or type(raw_exclude_keywords) is not tuple:
            raise _value_error()

        include_roots: list[ConfluenceIncludeRoot] = []
        include_ids: list[str] = []
        for root in raw_include_roots:
            if type(root) is not ConfluenceIncludeRoot:
                raise _value_error()
            page_id = root.page_id
            name = root.name
            if type(page_id) is not str or not page_id:
                raise _value_error()
            if name is not None and type(name) is not str:
                raise _value_error()
            include_roots.append(ConfluenceIncludeRoot(page_id=page_id, name=name))
            include_ids.append(page_id)

        exclude_subtrees: list[ConfluenceExcludeSubtree] = []
        exclude_ids: list[str] = []
        for subtree in raw_exclude_subtrees:
            if type(subtree) is not ConfluenceExcludeSubtree:
                raise _value_error()
            page_id = subtree.page_id
            reason = subtree.reason
            if type(page_id) is not str or not page_id:
                raise _value_error()
            if reason is not None and type(reason) is not str:
                raise _value_error()
            exclude_subtrees.append(
                ConfluenceExcludeSubtree(page_id=page_id, reason=reason)
            )
            exclude_ids.append(page_id)
        for keyword in raw_include_keywords + raw_exclude_keywords:
            if type(keyword) is not str:
                raise _value_error()
        if len(include_ids) != len(set(include_ids)) or len(exclude_ids) != len(set(exclude_ids)):
            raise _value_error()
        if set(include_ids).intersection(exclude_ids):
            raise _value_error()
    except (AttributeError, TypeError, ValueError):
        raise _value_error() from None
    return _ValidatedSourceConfig(
        space_key=space_key,
        page_size=page_size,
        include_roots=tuple(include_roots),
        exclude_subtrees=tuple(exclude_subtrees),
        include_keywords=tuple(raw_include_keywords),
        exclude_keywords=tuple(raw_exclude_keywords),
    )


def _endpoint_identity_digest(endpoint_url: object) -> str:
    if type(endpoint_url) is not str or not endpoint_url:
        raise _type_error() if type(endpoint_url) is not str else _value_error()
    if any(
        character.isspace() or unicodedata.category(character) in {"Cc", "Cf"}
        for character in endpoint_url
    ):
        raise _value_error()
    try:
        parsed = urlsplit(endpoint_url)
        if (
            parsed.scheme.lower() != "https"
            or "?" in endpoint_url
            or "#" in endpoint_url
            or "@" in parsed.netloc
        ):
            raise _value_error()
        host = parsed.hostname
        if not host:
            raise _value_error()
        try:
            port = parsed.port
        except ValueError:
            raise _value_error() from None
        if parsed.netloc.endswith(":"):
            raise _value_error()
        normalized_host = host.encode("idna").decode("ascii").lower()
        if normalized_host.endswith("."):
            normalized_host = normalized_host[:-1]
        if not normalized_host:
            raise _value_error()
        normalized_port = 443 if port is None else port
        path = parsed.path or "/"
        while len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        preimage = "\x1f".join(("https", normalized_host, str(normalized_port), path))
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()
    except (UnicodeError, ValueError, TypeError):
        raise _value_error() from None


def _scope_digest(source_config: _ValidatedSourceConfig) -> str:
    labels = sorted(
        ({"page_id": root.page_id, "name": root.name} for root in source_config.include_roots),
        key=lambda entry: entry["page_id"],
    )
    reasons = sorted(
        ({"page_id": subtree.page_id, "reason": subtree.reason} for subtree in source_config.exclude_subtrees),
        key=lambda entry: entry["page_id"],
    )
    canonical = {
        "exclude_keywords": sorted(set(source_config.exclude_keywords)),
        "excluded_subtree_reasons": reasons,
        "include_keywords": sorted(set(source_config.include_keywords)),
        "include_root_labels": labels,
    }
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (UnicodeError, ValueError, TypeError):
        raise _value_error() from None
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, repr=False, init=False)
class ConfluenceCrawlFingerprint:
    """Opaque immutable lowercase SHA-256 crawl fingerprint."""

    _value: str = field(init=False, repr=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("ConfluenceCrawlFingerprint is builder-created")

    @property
    def value(self) -> str:
        return self._value

    @classmethod
    def _from_digest(cls, value: str) -> "ConfluenceCrawlFingerprint":
        if type(value) is not str or len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise _value_error()
        instance = object.__new__(cls)
        object.__setattr__(instance, "_value", value)
        return instance

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def __str__(self) -> str:
        return f"{type(self).__name__}()"


class ConfluenceCrawlFingerprintBuilder:
    """Build one fingerprint from trusted, already in-memory inputs."""

    @staticmethod
    def build(
        endpoint_url: str,
        source_config: ConfluenceSourceConfig,
        reliability_profile: Mapping[str, object],
    ) -> ConfluenceCrawlFingerprint:
        return _build_effective_crawl_input(
            endpoint_url, source_config, reliability_profile
        ).fingerprint


def _build_effective_crawl_input(
    endpoint_url: str,
    source_config: ConfluenceSourceConfig,
    reliability_profile: Mapping[str, object],
) -> _EffectiveCrawlInput:
    """Capture and validate every fingerprint input exactly once."""
    config = _validate_source_config(source_config)
    profile = _validate_profile(reliability_profile)
    if config.page_size != profile["inventory_page_size"]:
        raise _value_error()
    if len(config.include_roots) > profile["max_include_roots"]:
        raise _value_error()
    canonical_root_ids = tuple(sorted(root.page_id for root in config.include_roots))
    endpoint_digest = _endpoint_identity_digest(endpoint_url)
    scope_digest = _scope_digest(config)

    canonical: dict[str, object] = dict(_REGISTRY_CONSTANTS)
    canonical.update(
        {
            "endpoint_identity_sha256": endpoint_digest,
            "space_key": config.space_key,
            "scope_config_digest": scope_digest,
            "reliability_profile_id": profile["profile_id"],
            "reliability_profile_version": profile["profile_version"],
            "include_root_page_ids": list(canonical_root_ids),
            "excluded_subtree_page_ids": sorted(subtree.page_id for subtree in config.exclude_subtrees),
        }
    )
    canonical.update({key: profile[key] for key in _FINAL_PROFILE_INT_KEYS})
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (UnicodeError, ValueError, TypeError):
        raise _value_error() from None
    return _EffectiveCrawlInput(
        fingerprint=ConfluenceCrawlFingerprint._from_digest(
            hashlib.sha256(encoded).hexdigest()
        ),
        canonical_include_root_ids=canonical_root_ids,
        max_include_roots=int(profile["max_include_roots"]),
        inventory_page_size=int(profile["inventory_page_size"]),
        max_pages_per_run=int(profile["max_pages_per_run"]),
        max_inventory_windows_per_root=int(
            profile["max_inventory_windows_per_root"]
        ),
        max_inventory_windows_per_run=int(
            profile["max_inventory_windows_per_run"]
        ),
    )


def build_confluence_crawl_fingerprint(
    endpoint_url: str,
    source_config: ConfluenceSourceConfig,
    reliability_profile: Mapping[str, object],
) -> ConfluenceCrawlFingerprint:
    """Build an opaque M7 crawl fingerprint without performing I/O."""

    return ConfluenceCrawlFingerprintBuilder.build(
        endpoint_url, source_config, reliability_profile
    )


__all__ = [
    "ConfluenceCrawlFingerprint",
    "ConfluenceCrawlFingerprintBuilder",
    "build_confluence_crawl_fingerprint",
]
