"""Typed, schema-validated handoffs used by the M10 composition gate."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Protocol

from .confluence_crawl_run import CrawlRunId
from .m10_snapshot import M10SnapshotError, M10SnapshotMetrics, M10SnapshotProjection, M10SnapshotRequest

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_JIRA = re.compile(r"^jira:issue:[A-Z][A-Z0-9_]*-[0-9]+$")
_PAGE_TARGET = re.compile(r"^confluence:page:[^\s:]+$")
_MEDIA_TARGET = re.compile(r"^confluence:attachment:[^\s:]+$")
_HANDOFF_FIELDS = {"run_id", "generation_id", "source_version", "documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "raw_artifact_identity", "errors"}
_GIT_FIELDS = {"repository", "branch", "commit", "documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "errors"}
_RESULT_FIELDS = {"projection", "failure_category"}
_RELATION_STATUSES = {"resolved", "unresolved_without_jira_api", "deferred_mvp", "unresolved_target"}
_MEDIA_STATUSES = {"parsed", "ocr", "summarized", "not_processed", "failed"}
_SCHEMAS = {"documents": "CanonicalDocument", "chunks": "ChunkRecord", "relations": "RelationRecord", "acl": "ACLRecord", "media_assets": "MediaAsset", "symbols": "SymbolRecord", "sync_state": "SyncStateRecord"}
_IDS = {"documents": "document_id", "chunks": "chunk_id", "relations": "relation_id", "acl": "acl_id", "media_assets": "media_id", "symbols": "symbol_id", "sync_state": "entity_id"}


class M10SchemaValidator(Protocol):
    def validate_record(self, schema_name: str, record: dict[str, object]) -> None: ...


def _guard(value: object, cls: type, fields: set[str]) -> None:
    if type(value) is not cls:
        raise TypeError(f"{cls.__name__} expects exact type")
    try:
        actual = set(vars(value))
    except Exception:
        raise TypeError(f"{cls.__name__} has invalid fields") from None
    if actual != fields:
        raise ValueError(f"{cls.__name__} has invalid fields")


def _records(name: str, value: object) -> tuple[dict[str, object], ...]:
    if type(value) is not tuple or any(type(item) is not dict for item in value):
        raise M10SnapshotError(f"{name} must be tuple of records")
    return tuple(copy.deepcopy(item) for item in value)


def _errors(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(x) is not str or not x or "\n" in x or "\r" in x for x in value):
        raise M10SnapshotError("errors must be sanitized tuple")
    return tuple(value)


@dataclass(frozen=True)
class M10ConfluenceHandoff:
    run_id: CrawlRunId
    generation_id: CrawlRunId
    source_version: str
    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    relations: tuple[dict[str, object], ...]
    acl: tuple[dict[str, object], ...]
    media_assets: tuple[dict[str, object], ...]
    symbols: tuple[dict[str, object], ...]
    sync_state: tuple[dict[str, object], ...]
    raw_artifact_identity: str
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _guard(self, M10ConfluenceHandoff, _HANDOFF_FIELDS)
        if type(self.run_id) is not CrawlRunId or type(self.generation_id) is not CrawlRunId or self.run_id != self.generation_id:
            raise M10SnapshotError("Confluence run/generation mismatch")
        if type(self.source_version) is not str or not self.source_version or "\n" in self.source_version:
            raise M10SnapshotError("invalid Confluence source version")
        if type(self.raw_artifact_identity) is not str or not self.raw_artifact_identity or "\n" in self.raw_artifact_identity:
            raise M10SnapshotError("invalid raw artifact identity")
        for name in _SCHEMAS:
            object.__setattr__(self, name, _records(name, getattr(self, name)))
        object.__setattr__(self, "errors", _errors(self.errors))


@dataclass(frozen=True)
class M10GitHandoff:
    repository: str
    branch: str
    commit: str
    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    relations: tuple[dict[str, object], ...]
    acl: tuple[dict[str, object], ...]
    media_assets: tuple[dict[str, object], ...]
    symbols: tuple[dict[str, object], ...]
    sync_state: tuple[dict[str, object], ...]
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _guard(self, M10GitHandoff, _GIT_FIELDS)
        if type(self.repository) is not str or not self.repository or type(self.branch) is not str or not self.branch or type(self.commit) is not str or not _HEX40.fullmatch(self.commit):
            raise M10SnapshotError("invalid Git identity")
        for name in _SCHEMAS:
            object.__setattr__(self, name, _records(name, getattr(self, name)))
        object.__setattr__(self, "errors", _errors(self.errors))


class M10ConfluenceAdapter(Protocol):
    def collect(self, request: M10SnapshotRequest) -> M10ConfluenceHandoff: ...


class M10GitAdapter(Protocol):
    def collect(self, request: M10SnapshotRequest) -> M10GitHandoff: ...


def _identity(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if type(value) is not str or not value:
        raise M10SnapshotError(f"record missing {field}")
    return value


def _path(value: object) -> str:
    if type(value) is not str or not value or value.startswith("/") or "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise M10SnapshotError("invalid POSIX file path")
    return value


def _validate_records(streams: dict[str, tuple[dict[str, object], ...]], injected_validator: M10SchemaValidator, canonical_validator: M10SchemaValidator) -> dict[str, tuple[dict[str, object], ...]]:
    if not callable(getattr(injected_validator, "validate_record", None)) or not callable(getattr(canonical_validator, "validate_record", None)):
        raise TypeError("schema validator is invalid")
    clean: dict[str, tuple[dict[str, object], ...]] = {}
    for name, schema in _SCHEMAS.items():
        untouched = []
        for record in streams[name]:
            if type(record) is not dict:
                raise M10SnapshotError(f"{name} record is invalid")
            validation_copy = copy.deepcopy(record)
            canonical_before = copy.deepcopy(validation_copy)
            try:
                canonical_validator.validate_record(schema, validation_copy)
            except Exception:
                raise M10SnapshotError(f"{name} canonical validation failed") from None
            if validation_copy != canonical_before:
                raise M10SnapshotError(f"{name} canonical validator mutated record")
            projection_copy = copy.deepcopy(record)
            try:
                injected_validator.validate_record(schema, projection_copy)
            except Exception:
                raise M10SnapshotError(f"{name} injected validation failed") from None
            if projection_copy != record:
                raise M10SnapshotError(f"{name} injected validator mutated record")
            untouched.append(copy.deepcopy(record))
        clean[name] = tuple(untouched)
    return clean


def _require_canonical_validator(value: object) -> M10SchemaValidator:
    from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
    if type(value) is not FoundationSchemaValidator:
        raise TypeError("canonical validator must be the shared FoundationSchemaValidator")
    if not callable(getattr(value, "validate_record", None)):
        raise TypeError("canonical validator is invalid")
    return value


def _handoff_ownership(name: str, streams: dict[str, tuple[dict[str, object], ...]], request: M10SnapshotRequest) -> None:
    allowed = {"documents", "chunks", "acl", "media_assets", "relations"} if name == "confluence" else {"documents", "chunks", "acl", "symbols"}
    forbidden = set(_SCHEMAS) - allowed - {"sync_state"}
    for stream in forbidden:
        if streams[stream]:
            raise M10SnapshotError(f"{name} handoff contains forbidden {stream}")
    for stream in allowed - {"relations", "symbols"}:
        for record in streams[stream]:
            if record.get("source_system") != name:
                raise M10SnapshotError(f"{name} handoff source ownership drift")
    if name == "confluence":
        docs = {_identity(row, "document_id") for row in streams["documents"]}
        chunks = {_identity(row, "chunk_id") for row in streams["chunks"]}
        for row in streams["relations"]:
            if row.get("source_id") not in docs and row.get("source_id") not in chunks:
                raise M10SnapshotError("Confluence relation source ownership drift")
        for row in streams["sync_state"]:
            if row.get("source_id") != request.confluence_scope.source_id or row.get("entity_type") not in {"page", "attachment"}:
                raise M10SnapshotError("Confluence sync ownership drift")
    else:
        if streams["relations"] or streams["media_assets"]:
            raise M10SnapshotError("Git handoff contains forbidden stream")
        for row in streams["sync_state"]:
            if row.get("source_id") != request.git_repository or row.get("entity_type") not in {"file", "repo"}:
                raise M10SnapshotError("Git sync ownership drift")


def compose_m10_projection(request: M10SnapshotRequest, confluence: M10ConfluenceHandoff, git: M10GitHandoff, *, schema_validator: M10SchemaValidator, canonical_schema_validator: M10SchemaValidator | None = None) -> M10SnapshotProjection:
    """Merge trusted handoffs atomically in memory; this function performs no I/O."""
    if type(request) is not M10SnapshotRequest:
        raise TypeError("request expects M10SnapshotRequest")
    M10SnapshotRequest.__post_init__(request)
    if type(confluence) is not M10ConfluenceHandoff or type(git) is not M10GitHandoff:
        raise TypeError("invalid handoff")
    M10ConfluenceHandoff.__post_init__(confluence)
    M10GitHandoff.__post_init__(git)
    if canonical_schema_validator is None:
        from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator
        canonical_schema_validator = FoundationSchemaValidator()
    canonical_schema_validator = _require_canonical_validator(canonical_schema_validator)
    if not callable(getattr(schema_validator, "validate_record", None)) or not callable(getattr(canonical_schema_validator, "validate_record", None)):
        raise TypeError("schema validator is invalid")
    if confluence.run_id != request.run_id or confluence.generation_id != request.generation_id or confluence.raw_artifact_identity != request.raw_generation_id:
        raise M10SnapshotError("Confluence provenance drift")
    if (git.repository, git.branch, git.commit) != (request.git_repository, request.git_branch, request.git_commit):
        raise M10SnapshotError("Git provenance drift")
    if confluence.errors or git.errors:
        raise M10SnapshotError("adapter handoff contains errors")
    confluence_streams = {name: getattr(confluence, name) for name in _SCHEMAS}
    git_streams = {name: getattr(git, name) for name in _SCHEMAS}
    _validate_records(confluence_streams, schema_validator, canonical_schema_validator)
    _validate_records(git_streams, schema_validator, canonical_schema_validator)
    _handoff_ownership("confluence", confluence_streams, request)
    _handoff_ownership("git", git_streams, request)
    streams = _validate_records({name: tuple(confluence_streams[name] + git_streams[name]) for name in _SCHEMAS}, schema_validator, canonical_schema_validator)
    ids: dict[str, set[str]] = {}
    for name, field in _IDS.items():
        values = tuple(_identity(record, field) for record in streams[name])
        if len(values) != len(set(values)):
            raise M10SnapshotError(f"duplicate {name} identity")
        ids[name] = set(values)
    documents = streams["documents"]
    confluence_pages: list[str] = []
    for record in documents:
        source = record["source_system"]
        if source == "confluence":
            page = record.get("page_id")
            if type(page) is not str or page not in request.ordered_page_ids or record.get("source_version") != confluence.source_version:
                raise M10SnapshotError("Confluence document provenance is invalid")
            confluence_pages.append(page)
        elif source == "git":
            if record.get("repo") != request.git_repository or record.get("branch") != request.git_branch or record.get("source_version") != request.git_commit:
                raise M10SnapshotError("Git document provenance is invalid")
            _path(record.get("file_path"))
        else:
            raise M10SnapshotError("document source ownership is invalid")
    page_positions = [request.ordered_page_ids.index(page) for page in confluence_pages]
    if page_positions != sorted(page_positions) or len(set(confluence_pages)) != len(confluence_pages):
        raise M10SnapshotError("Confluence page ordering is invalid")
    acl_by_document: dict[str, dict[str, object]] = {}
    for record in streams["acl"]:
        document_id = _identity(record, "document_id")
        document = next((doc for doc in documents if doc["document_id"] == document_id), None)
        tags = record.get("acl_tags")
        if document_id in acl_by_document or document is None or record.get("source_system") != document.get("source_system") or record.get("acl_id") != document.get("acl_id") or type(tags) is not list or not tags or any(type(tag) is not str or not tag for tag in tags):
            raise M10SnapshotError("ACL cardinality or ownership is invalid")
        if document.get("source_system") == "git" and tags != [f"repo:{request.git_repository}"]:
            raise M10SnapshotError("Git ACL is not deny-safe")
        acl_by_document[document_id] = record
    if set(acl_by_document) != ids["documents"]:
        raise M10SnapshotError("every document requires one ACL")
    for record in streams["chunks"]:
        parent = record.get("document_id")
        if parent not in ids["documents"] or record.get("source_system") != next(doc["source_system"] for doc in documents if doc["document_id"] == parent):
            raise M10SnapshotError("chunk parent/source is invalid")
        parent_acl = acl_by_document[parent].get("acl_tags")
        if record.get("acl_tags") != parent_acl:
            raise M10SnapshotError("chunk ACL inheritance is invalid")
        if record.get("source_system") == "confluence" and (record.get("page_id") not in request.ordered_page_ids or record.get("page_id") != next(doc.get("page_id") for doc in documents if doc["document_id"] == parent) or record.get("source_version") != confluence.source_version):
            raise M10SnapshotError("Confluence chunk provenance is invalid")
        if record.get("source_system") == "git" and (record.get("repo") != request.git_repository or record.get("branch") != request.git_branch or record.get("source_version") != request.git_commit or record["acl_tags"] != [f"repo:{request.git_repository}"]):
            raise M10SnapshotError("Git chunk ACL/provenance is invalid")
        if record.get("source_system") == "git":
            _path(record.get("file_path"))
    for record in streams["relations"]:
        source = record.get("source_id")
        target = record.get("target_id")
        status = record.get("resolution_status")
        if source not in ids["documents"] and source not in ids["chunks"]:
            raise M10SnapshotError("relation source is missing")
        if status not in _RELATION_STATUSES or type(target) is not str or not target or target.strip() != target or target.lower() in {"unknown", "none", "null", "unresolved"}:
            raise M10SnapshotError("relation status/target is invalid")
        if record.get("relation_type") == "mentions_jira_key" and _JIRA.fullmatch(target) is None:
            raise M10SnapshotError("Jira relation target marker is invalid")
        if status != "resolved":
            grammar = {"mentions_jira_key": _JIRA, "includes_page": _PAGE_TARGET, "links_to_page": _PAGE_TARGET, "embeds_media": _MEDIA_TARGET}.get(record.get("relation_type"))
            if grammar is None or grammar.fullmatch(target) is None:
                raise M10SnapshotError("external relation target grammar is invalid")
        if status == "resolved" and (target not in set().union(*ids.values()) or target.startswith("jira:issue:")):
            raise M10SnapshotError("resolved relation target is invalid")
        if status != "resolved" and (target in set().union(*ids.values()) or (record.get("relation_type") == "mentions_jira_key" and not _JIRA.fullmatch(target))):
            raise M10SnapshotError("unresolved relation target is invalid")
    for record in streams["media_assets"]:
        if not request.media_policy.include_attachments or len(streams["media_assets"]) > request.media_policy.max_assets:
            raise M10SnapshotError("media policy or budget is invalid")
        parent = record.get("parent_document_id")
        parent_record = next((doc for doc in documents if doc["document_id"] == parent), None)
        if parent_record is None or parent_record.get("source_system") != "confluence" or record.get("source_system") != "confluence" or record.get("source_version") != confluence.source_version or record.get("processing_status") not in request.media_policy.allowed_processing_statuses:
            raise M10SnapshotError("media provenance/policy is invalid")
        downloaded = record.get("download_status") == "downloaded"
        content_hash, raw_uri = record.get("content_hash"), record.get("raw_uri")
        attachment_id = record["media_id"].split(":", 2)[-1]
        if (content_hash is None) != (raw_uri is None) or downloaded != (content_hash is not None and raw_uri is not None) or (content_hash is not None and (type(content_hash) is not str or not _HEX64.fullmatch(content_hash) or type(raw_uri) is not str or raw_uri != f"raw://confluence/attachments/{attachment_id}/{content_hash}")):
            raise M10SnapshotError("media raw/content provenance is invalid")
    git_files = {(doc.get("repo"), doc.get("branch"), doc.get("source_version"), doc.get("file_path")) for doc in documents if doc.get("source_system") == "git"}
    for record in streams["symbols"]:
        if (record.get("repo"), record.get("branch"), record.get("commit_hash"), _path(record.get("file_path"))) not in git_files:
            raise M10SnapshotError("symbol provenance is invalid")
        if type(record.get("line_start")) is not int or type(record.get("line_end")) is not int or record["line_start"] < 1 or record["line_end"] < record["line_start"]:
            raise M10SnapshotError("symbol line span is invalid")
        if record.get("chunk_id") is not None and record["chunk_id"] not in ids["chunks"]:
            raise M10SnapshotError("symbol chunk linkage is missing")
    entity_ids = set().union(*ids.values())
    sync_seen: set[str] = set()
    for record in streams["sync_state"]:
        entity = record.get("entity_id")
        repo_sync = record.get("entity_type") == "repo" and record.get("source_id") == request.git_repository and entity == request.git_repository
        if entity in sync_seen or (entity not in entity_ids and not repo_sync) or record.get("status") != "active" or record.get("schema_version") != "1.0":
            raise M10SnapshotError("sync state is invalid")
        sync_seen.add(entity)
        matching = next((row for row in documents if row["document_id"] == entity), None) or next((row for row in streams["media_assets"] if row["media_id"] == entity), None)
        if matching is None and not repo_sync:
            raise M10SnapshotError("sync entity is not emitted")
        if repo_sync:
            expected_source, expected_type, expected_version = request.git_repository, "repo", request.git_commit
        else:
            expected_source = request.confluence_scope.source_id if matching.get("source_system") == "confluence" else request.git_repository
            expected_type = "page" if matching.get("source_system") == "confluence" and entity.startswith("confluence:page:") else "attachment" if matching.get("source_system") == "confluence" else "file"
            expected_version = matching.get("source_version")
        if record.get("source_id") != expected_source or record.get("entity_type") != expected_type:
            raise M10SnapshotError("sync source/entity type is invalid")
        if expected_version is not None and record.get("last_seen_version") != expected_version:
            raise M10SnapshotError("sync version drift")
    ordered = {name: tuple(sorted(value, key=lambda record: _identity(record, _IDS[name]))) for name, value in streams.items()}
    media_processed = sum(1 for row in ordered["media_assets"] if row["processing_status"] in {"parsed", "ocr", "summarized"})
    media_failed = sum(1 for row in ordered["media_assets"] if row["processing_status"] == "failed")
    confluence_documents = sum(1 for row in ordered["documents"] if row["source_system"] == "confluence")
    git_documents = sum(1 for row in ordered["documents"] if row["source_system"] == "git")
    metrics = M10SnapshotMetrics(len(ordered["documents"]), len(ordered["chunks"]), len(ordered["relations"]), len(ordered["acl"]), len(ordered["media_assets"]), len(ordered["symbols"]), len(ordered["sync_state"]), 0, confluence_documents, git_documents, sum(1 for row in ordered["relations"] if row["resolution_status"] != "resolved"), media_processed, media_failed, sum(1 for row in ordered["symbols"] if row.get("chunk_id") is not None), sum(1 for row in ordered["chunks"] if not row["acl_tags"]))
    return M10SnapshotProjection.from_request(request, dataset_name="spen_knowledge_poc", schemas_version="1.0", source_scopes={"confluence": {"source_id": request.confluence_scope.source_id, "space_keys": request.confluence_scope.space_keys, "root_page_ids": request.confluence_scope.root_page_ids, "page_ids": request.confluence_scope.page_ids}, "git": {"repository": request.git_repository, "branch": request.git_branch, "commit": request.git_commit}}, documents=ordered["documents"], chunks=ordered["chunks"], relations=ordered["relations"], acl=ordered["acl"], media_assets=ordered["media_assets"], symbols=ordered["symbols"], sync_state=ordered["sync_state"], tombstones=(), metrics=metrics)


__all__ = ["M10SchemaValidator", "M10ConfluenceHandoff", "M10GitHandoff", "M10ConfluenceAdapter", "M10GitAdapter", "compose_m10_projection"]
