"""Runtime-validated wire models for the M10 full-snapshot seam."""
from __future__ import annotations

import re
import unicodedata
import copy
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .confluence_crawl_run import CrawlRunId
from .one_page_export import OnePageExportProfileBundle, _canonical_config_hash
from knowledgenexus.foundation.domain.rules.text_normalization import TextNormalizationRules
from .chunk_stability import ACTIVE_CHUNKER_VERSION
from .chunking_profile import ChunkingProfile
from .jira_relation_profile import JiraRelationProfile

M10_DATASET_NAME = "spen_knowledge_poc"
M10_SCHEMAS_VERSION = "1.0"
M10_EXPORT_MODE = "full_snapshot"
M10_COUNT_KEYS = ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_POSIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_PROCESSING = ("failed", "not_processed", "ocr", "parsed", "summarized")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_CONCRETE_PATH_TYPE = type(Path())

class M10SnapshotError(ValueError):
    pass

def _identifier(name: str, value: object) -> str:
    if type(value) is not str or not value or "\n" in value or "\r" in value or unicodedata.normalize("NFC", value) != value:
        raise M10SnapshotError(f"{name} must be a canonical one-line identifier")
    return value

def _tuple(name: str, value: object, *, nonempty: bool = False) -> tuple:
    if type(value) is not tuple or (nonempty and not value):
        raise M10SnapshotError(f"{name} expects tuple")
    return tuple(value)

def _counts(value: object, name: str = "metrics") -> dict[str, int]:
    if type(value) is not dict or set(value) != set(M10_COUNT_KEYS):
        raise M10SnapshotError(f"{name} has wrong fields")
    out = {}
    for key in M10_COUNT_KEYS:
        v = value[key]
        if type(v) is not int or v < 0:
            raise M10SnapshotError(f"{name}[{key}] must be non-negative int")
        out[key] = v
    return out

def _guard(value: object, cls: type) -> None:
    if type(value) is not cls:
        raise TypeError(f"{cls.__name__} expects exact type")
    try:
        expected = set(cls.__dataclass_fields__)
        actual = set(vars(value))
    except Exception:
        raise TypeError(f"{cls.__name__} has invalid fields") from None
    if actual != expected:
        raise ValueError(f"{cls.__name__} has invalid fields")

def _timestamp(value: object) -> str:
    if type(value) is not str or not _RFC3339.fullmatch(value):
        raise M10SnapshotError("generated_at must be strict RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise M10SnapshotError("generated_at must be strict RFC3339") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise M10SnapshotError("generated_at requires timezone")
    return value

def _is_reparse_point(path: Path) -> bool:
    try:
        return bool(getattr(os.stat(path), "st_file_attributes", 0) & 0x40000000)
    except (OSError, ValueError, TypeError):
        raise M10SnapshotError("unsafe dataset_root") from None

@dataclass(frozen=True)
class M10ProfileIdentity:
    normalized_embedding_profile_text: str
    normalized_jira_relation_profile_text: str
    def __post_init__(self):
        _guard(self, M10ProfileIdentity)
        for name in ("normalized_embedding_profile_text", "normalized_jira_relation_profile_text"):
            value = getattr(self, name)
            if type(value) is not str or TextNormalizationRules.normalize_text(value) != value:
                raise M10SnapshotError(f"{name} must be canonical-normalized text")

    @property
    def config_hash(self) -> str:
        return _canonical_config_hash(
            embedding_profile_text=self.normalized_embedding_profile_text,
            jira_relation_profile_text=self.normalized_jira_relation_profile_text,
        )

@dataclass(frozen=True)
class M10ConfluenceScope:
    source_id: str
    space_keys: tuple[str, ...]
    root_page_ids: tuple[str, ...]
    page_ids: tuple[str, ...]
    def __post_init__(self):
        _guard(self, M10ConfluenceScope)
        _identifier("source_id", self.source_id)
        for n, val in (("space_keys", self.space_keys), ("root_page_ids", self.root_page_ids), ("page_ids", self.page_ids)):
            vals = _tuple(n, val, nonempty=True)
            if any(type(x) is not str or not x or unicodedata.normalize("NFC", x) != x for x in vals) or len(set(vals)) != len(vals) or tuple(sorted(vals)) != vals:
                raise M10SnapshotError(f"{n} must be sorted unique identifiers")
            object.__setattr__(self, n, vals)
        if not set(self.root_page_ids).issubset(self.page_ids):
            raise M10SnapshotError("roots must be in page scope")

@dataclass(frozen=True)
class M10ConfluenceExclusion:
    page_id: str
    reason: Literal["exclude_subtree", "exclude_page"]
    def __post_init__(self):
        _guard(self, M10ConfluenceExclusion)
        _identifier("page_id", self.page_id)
        if type(self.reason) is not str or self.reason not in ("exclude_subtree", "exclude_page"):
            raise M10SnapshotError("invalid exclusion reason")

@dataclass(frozen=True)
class M10MediaPolicy:
    include_attachments: bool
    allow_download: bool
    allowed_processing_statuses: tuple[str, ...]
    max_assets: int
    def __post_init__(self):
        _guard(self, M10MediaPolicy)
        if type(self.include_attachments) is not bool or type(self.allow_download) is not bool:
            raise M10SnapshotError("media flags must be bool")
        vals = _tuple("allowed_processing_statuses", self.allowed_processing_statuses)
        if any(type(x) is not str or x not in _PROCESSING for x in vals) or len(set(vals)) != len(vals) or tuple(sorted(vals)) != vals:
            raise M10SnapshotError("invalid processing statuses")
        if type(self.max_assets) is not int or self.max_assets < 0:
            raise M10SnapshotError("max_assets must be non-negative int")
        if self.allow_download and not self.include_attachments:
            raise M10SnapshotError("download requires attachments")
        object.__setattr__(self, "allowed_processing_statuses", vals)

@dataclass(frozen=True)
class M10SnapshotRequest:
    run_id: CrawlRunId; generation_id: CrawlRunId; confluence_scope: M10ConfluenceScope
    confluence_exclusions: tuple[M10ConfluenceExclusion, ...]; ordered_page_ids: tuple[str, ...]
    raw_generation_id: str; git_repository: str; git_branch: str; git_commit: str
    media_policy: M10MediaPolicy; profile_bundle: OnePageExportProfileBundle; generated_at: str
    dataset_root: Path; export_mode: str
    profile_identity: M10ProfileIdentity | None = None
    def __post_init__(self):
        _guard(self, M10SnapshotRequest)
        if type(self.profile_identity) is not M10ProfileIdentity:
            raise M10SnapshotError("profile_identity is required")
        M10ProfileIdentity.__post_init__(self.profile_identity)
        if type(self.run_id) is not CrawlRunId or type(self.generation_id) is not CrawlRunId or self.run_id != self.generation_id:
            raise M10SnapshotError("run/generation identity mismatch")
        if type(self.confluence_scope) is not M10ConfluenceScope or type(self.media_policy) is not M10MediaPolicy or type(self.profile_bundle) is not OnePageExportProfileBundle:
            raise M10SnapshotError("invalid nested request model")
        try:
            M10ConfluenceScope.__post_init__(self.confluence_scope)
            M10MediaPolicy.__post_init__(self.media_policy)
        except (TypeError, ValueError):
            raise M10SnapshotError("invalid nested request model") from None
        if set(vars(self.profile_bundle)) != {"chunking_profile", "jira_relation_profile", "config_hash"} or type(self.profile_bundle.chunking_profile) is not ChunkingProfile or type(self.profile_bundle.jira_relation_profile) is not JiraRelationProfile or type(self.profile_bundle.config_hash) is not str or not _HEX64.fullmatch(self.profile_bundle.config_hash):
            raise M10SnapshotError("invalid profile bundle")
        try:
            _guard(self.profile_bundle.chunking_profile, ChunkingProfile)
            ChunkingProfile.__post_init__(self.profile_bundle.chunking_profile)
            _guard(self.profile_bundle.jira_relation_profile, JiraRelationProfile)
            JiraRelationProfile.__post_init__(self.profile_bundle.jira_relation_profile)
        except (TypeError, ValueError):
            raise M10SnapshotError("invalid profile bundle") from None
        if self.profile_bundle.config_hash != self.profile_identity.config_hash:
            raise M10SnapshotError("profile config hash mismatch")
        ex = _tuple("confluence_exclusions", self.confluence_exclusions)
        if any(type(x) is not M10ConfluenceExclusion for x in ex) or len({x.page_id for x in ex}) != len(ex): raise M10SnapshotError("invalid exclusions")
        for item in ex:
            try: M10ConfluenceExclusion.__post_init__(item)
            except (TypeError, ValueError): raise M10SnapshotError("invalid exclusions") from None
        pages = _tuple("ordered_page_ids", self.ordered_page_ids)
        if any(type(x) is not str for x in pages) or len(set(pages)) != len(pages) or not set(pages).issubset(self.confluence_scope.page_ids): raise M10SnapshotError("invalid ordered pages")
        _identifier("raw_generation_id", self.raw_generation_id)
        for n in ("git_repository", "git_branch"):
            if type(getattr(self, n)) is not str or not _POSIX.fullmatch(getattr(self, n)): raise M10SnapshotError(f"invalid {n}")
        if type(self.git_commit) is not str or not _HEX40.fullmatch(self.git_commit): raise M10SnapshotError("invalid git_commit")
        _timestamp(self.generated_at)
        if not isinstance(self.dataset_root, Path) or not self.dataset_root.is_absolute() or not self.dataset_root.exists() or not self.dataset_root.is_dir() or self.dataset_root.is_symlink() or _is_reparse_point(self.dataset_root): raise M10SnapshotError("unsafe dataset_root")
        if self.export_mode != M10_EXPORT_MODE: raise M10SnapshotError("invalid export_mode")
        object.__setattr__(self, "confluence_exclusions", ex); object.__setattr__(self, "ordered_page_ids", pages)

@dataclass(frozen=True)
class M10SnapshotMetrics:
    documents: int; chunks: int; relations: int; acl: int; media_assets: int; symbols: int; sync_state: int; tombstones: int
    confluence_documents: int; git_documents: int; unresolved_relations: int; media_processed: int; media_failed: int; symbols_resolved: int; default_deny_chunks: int
    def __post_init__(self):
        _guard(self, M10SnapshotMetrics)
        vals = {k: getattr(self, k) for k in M10_COUNT_KEYS + ("confluence_documents", "git_documents", "unresolved_relations", "media_processed", "media_failed", "symbols_resolved", "default_deny_chunks")}
        for k, v in vals.items():
            if type(v) is not int or v < 0: raise M10SnapshotError(f"{k} must be non-negative int")
        if self.confluence_documents + self.git_documents != self.documents or self.unresolved_relations > self.relations or self.media_processed + self.media_failed > self.media_assets or self.symbols_resolved > self.symbols or self.default_deny_chunks > self.chunks: raise M10SnapshotError("inconsistent snapshot metrics")

def _validated_metrics(value: object) -> M10SnapshotMetrics:
    if type(value) is not M10SnapshotMetrics or set(vars(value)) != set(M10SnapshotMetrics.__dataclass_fields__):
        raise M10SnapshotError("invalid snapshot metrics")
    try: rebuilt = M10SnapshotMetrics(**{k: getattr(value, k) for k in M10SnapshotMetrics.__dataclass_fields__})
    except Exception: raise M10SnapshotError("invalid snapshot metrics") from None
    if value != rebuilt: raise M10SnapshotError("invalid snapshot metrics")
    return rebuilt

@dataclass(frozen=True)
class M10SnapshotProjection:
    dataset_name: str; schemas_version: str; source_scopes: dict[str, object]; generated_at: str; config_hash: str; chunker_version: str; documents: tuple; chunks: tuple; relations: tuple; acl: tuple; media_assets: tuple; symbols: tuple; sync_state: tuple; tombstones: tuple; metrics: M10SnapshotMetrics
    export_mode: str = M10_EXPORT_MODE
    def __post_init__(self):
        _guard(self, M10SnapshotProjection)
        if self.dataset_name != M10_DATASET_NAME or self.schemas_version != M10_SCHEMAS_VERSION or type(self.source_scopes) is not dict: raise M10SnapshotError("invalid projection identity")
        _validated_metrics(self.metrics)
        if type(self.generated_at) is not str or type(self.config_hash) is not str or not _HEX64.fullmatch(self.config_hash) or self.chunker_version != ACTIVE_CHUNKER_VERSION or self.export_mode != M10_EXPORT_MODE: raise M10SnapshotError("invalid projection metadata")
        _timestamp(self.generated_at)
        scopes = self.source_scopes
        if set(scopes) - {"confluence", "git"} or "confluence" not in scopes or tuple(scopes) != tuple(sorted(scopes)):
            raise M10SnapshotError("invalid source scopes")
        for key, value in scopes.items():
            if type(value) is not dict:
                raise M10SnapshotError("source scope expects object")
            if key == "confluence":
                if set(value) != {"source_id", "space_keys", "root_page_ids", "page_ids"}:
                    raise M10SnapshotError("invalid confluence scope fields")
                M10ConfluenceScope(value["source_id"], tuple(value["space_keys"]), tuple(value["root_page_ids"]), tuple(value["page_ids"]))
            else:
                if set(value) != {"repository", "branch", "commit"} or type(value["repository"]) is not str or type(value["branch"]) is not str or type(value["commit"]) is not str or not _POSIX.fullmatch(value["repository"]) or not _POSIX.fullmatch(value["branch"]) or not _HEX40.fullmatch(value["commit"]):
                    raise M10SnapshotError("invalid git scope")
        for n in ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones"):
            val = _tuple(n, getattr(self, n));
            if any(type(x) is not dict for x in val): raise M10SnapshotError(f"{n} contains invalid record")
            object.__setattr__(self, n, tuple(copy.deepcopy(x) for x in val))
        object.__setattr__(self, "source_scopes", copy.deepcopy(self.source_scopes))

    @classmethod
    def from_request(cls, request: M10SnapshotRequest, **kwargs):
        if type(request) is not M10SnapshotRequest:
            raise TypeError("request expects M10SnapshotRequest")
        M10SnapshotRequest.__post_init__(request)
        supplied = kwargs.pop("chunker_version", request.profile_bundle.chunking_profile.chunker_version)
        if supplied != request.profile_bundle.chunking_profile.chunker_version:
            raise M10SnapshotError("chunker version mismatch")
        return cls(chunker_version=supplied, config_hash=request.profile_bundle.config_hash, generated_at=request.generated_at, **kwargs)

@dataclass(frozen=True)
class M10SnapshotResult:
    status: Literal["composed", "staged", "published", "failed"]
    metrics: M10SnapshotMetrics | None = None; digest: str | None = None; dataset_version: str | None = None; final_path: Path | None = None
    failure_category: Literal["invalid_request", "adapter", "projection", "staging", "completion", "publication", "acceptance"] | None = None
    def __post_init__(self):
        _guard(self, M10SnapshotResult)
        if type(self.status) is not str or self.status not in ("composed", "staged", "published", "failed"): raise M10SnapshotError("invalid result status")
        if self.status == "failed":
            if type(self.failure_category) is not str or self.failure_category not in ("invalid_request", "adapter", "projection", "staging", "completion", "publication", "acceptance") or any(x is not None for x in (self.metrics, self.digest, self.dataset_version, self.final_path)): raise M10SnapshotError("invalid failed result")
        else:
            _validated_metrics(self.metrics)
            if type(self.digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.digest) or self.failure_category is not None: raise M10SnapshotError("invalid successful result")
            if self.status == "composed" and self.dataset_version is not None: raise M10SnapshotError("composed result cannot have dataset version")
            if self.status in ("staged", "published") and (type(self.dataset_version) is not str or not self.dataset_version): raise M10SnapshotError("missing dataset version")
            if self.status == "published" and (type(self.final_path) is not _CONCRETE_PATH_TYPE or not self.final_path.is_absolute()): raise M10SnapshotError("missing final path")
            if self.status != "published" and self.final_path is not None: raise M10SnapshotError("unexpected final path")

@dataclass(frozen=True)
class M10QualityReportInput:
    active_profile: str; profile_status: str; chunker_version: str; expected_counts: dict[str, int]; source_scopes: dict[str, object]; jira_metrics: dict[str, object]; acl_metrics: dict[str, object]; media_metrics: dict[str, object]; symbol_metrics: dict[str, object]; sync_metrics: dict[str, object]; tombstone_metrics: dict[str, object]; completion_checks: dict[str, object]
    def __post_init__(self):
        _guard(self, M10QualityReportInput)
        for n in ("active_profile", "profile_status", "chunker_version"):
            if type(getattr(self, n)) is not str or not getattr(self, n): raise M10SnapshotError(f"{n} invalid")
        object.__setattr__(self, "expected_counts", _counts(self.expected_counts, "expected_counts"))
        for n in ("source_scopes", "jira_metrics", "acl_metrics", "media_metrics", "symbol_metrics", "sync_metrics", "tombstone_metrics", "completion_checks"):
            v = getattr(self, n)
            if type(v) is not dict or any(type(k) is not str for k in v): raise M10SnapshotError(f"{n} expects dict")
            object.__setattr__(self, n, dict(v))

__all__ = ["M10_DATASET_NAME", "M10_SCHEMAS_VERSION", "M10_EXPORT_MODE", "M10ConfluenceScope", "M10ConfluenceExclusion", "M10MediaPolicy", "M10SnapshotRequest", "M10SnapshotMetrics", "M10SnapshotProjection", "M10SnapshotResult", "M10QualityReportInput", "M10SnapshotError"]
