from __future__ import annotations

import copy
import inspect
from dataclasses import dataclass
from typing import Protocol

from knowledgenexus.foundation.application.use_cases.assemble_m10_handoffs import (
    AssembleConfluenceM10Handoff,
    AssembleGitM10Handoff,
    M10HandoffAssemblyError,
)
from knowledgenexus.foundation.domain.models.m10_composition import (
    M10ConfluenceHandoff,
    M10GitHandoff,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotRequest


class M10SourceAdapterError(Exception):
    """Sanitized public failure for an M10 source adapter."""


def _records(value: object, field_name: str) -> tuple[dict[str, object], ...]:
    if type(value) is not tuple or any(type(record) is not dict for record in value):
        raise ValueError(f"invalid {field_name}")
    return tuple(copy.deepcopy(record) for record in value)


@dataclass(frozen=True)
class ConfluenceMaterializedInput:
    source_version: str
    raw_artifact_identity: str
    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    relations: tuple[dict[str, object], ...]
    acl: tuple[dict[str, object], ...]
    media_assets: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        if type(self.source_version) is not str or not self.source_version or type(self.raw_artifact_identity) is not str or not self.raw_artifact_identity:
            raise ValueError("Confluence materialized provenance is invalid")
        for name in ("documents", "chunks", "relations", "acl", "media_assets"):
            object.__setattr__(self, name, _records(getattr(self, name), name))


@dataclass(frozen=True)
class GitMaterializedInput:
    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    acl: tuple[dict[str, object], ...]
    symbols: tuple[dict[str, object], ...] = ()

    def __post_init__(self) -> None:
        for name in ("documents", "chunks", "acl", "symbols"):
            object.__setattr__(self, name, _records(getattr(self, name), name))


class ConfluenceMaterializedSourcePort(Protocol):
    def collect(self, request: M10SnapshotRequest) -> ConfluenceMaterializedInput: ...


class GitMaterializedSourcePort(Protocol):
    def collect(self, request: M10SnapshotRequest) -> GitMaterializedInput: ...


def _stage_call(stage: object, *, request: M10SnapshotRequest, state: dict[str, object]) -> object:
    """Call an injected application seam without allowing arbitrary I/O here.

    Real adapters inject the already configured use-case (or a tiny facade
    around it).  The adapter only supplies immutable in-memory state and never
    accepts paths, credentials, or transport objects from the request.
    """
    method = getattr(stage, "execute", None)
    if callable(method):
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_kwargs = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())
        accepts_request_keyword = "request" in parameters
        if accepts_kwargs or accepts_request_keyword:
            return method(request=request, **state)
        return method(request)
    if callable(stage):
        try:
            parameters = inspect.signature(stage).parameters
        except (TypeError, ValueError):
            parameters = {}
        accepts_kwargs = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())
        return stage(request, **state) if accepts_kwargs or len(parameters) > 1 else stage(request)
    raise TypeError("provider stage is invalid")


def _field(value: object, name: str) -> object:
    if type(value) is dict:
        return value.get(name)
    return getattr(value, name, None)


def _records_from_result(value: object, names: tuple[str, ...], field_name: str) -> tuple[dict[str, object], ...]:
    """Extract records from direct outputs and the approved nested result models."""
    candidate = value
    for name in names:
        nested = _field(value, name)
        if nested is not None:
            candidate = nested
            break
    if candidate is not value:
        return _records(candidate, field_name)
    plan = _field(value, "plan")
    if plan is not None:
        for name in names:
            nested = _field(plan, name)
            if nested is not None:
                return _records(nested, field_name)
    return _records(candidate, field_name)


def _stage_records(value: object, names: tuple[str, ...], field_name: str) -> tuple[dict[str, object], ...]:
    candidate = value
    for name in names:
        nested = _field(value, name)
        if nested is not None:
            candidate = nested
            break
    return _records(candidate, field_name)


def _merge_records(left: tuple[dict[str, object], ...], right: tuple[dict[str, object], ...], *, identity: str) -> tuple[dict[str, object], ...]:
    merged: dict[str, dict[str, object]] = {}
    for record in (*left, *right):
        key = record.get(identity)
        if type(key) is not str or not key:
            raise ValueError(f"invalid {identity}")
        previous = merged.get(key)
        if previous is not None and previous != record:
            raise ValueError(f"conflicting {identity}")
        merged[key] = record
    return tuple(merged[key] for key in sorted(merged))


class ConfluenceM10MaterializedSource:
    """Compose the approved Confluence producers into an M10 source port.

    ``page_stage`` is the configured raw-page -> normalization/chunking facade.
    Optional stages enrich that result with generic/Jira relations, ACL, and
    media assets.  The provider is deliberately read-only: stages exchange
    copied tuples and the provider returns a validated ``ConfluenceMaterializedInput``.
    """

    def __init__(
        self,
        *,
        page_stage: object,
        relation_stage: object | None = None,
        acl_stage: object | None = None,
        media_stage: object | None = None,
    ) -> None:
        if not callable(getattr(page_stage, "execute", None)) and not callable(page_stage):
            raise TypeError("page_stage is invalid")
        for name, stage in (("relation_stage", relation_stage), ("acl_stage", acl_stage), ("media_stage", media_stage)):
            if stage is not None and not callable(getattr(stage, "execute", None)) and not callable(stage):
                raise TypeError(f"{name} is invalid")
        self._page_stage = page_stage
        self._relation_stage = relation_stage
        self._acl_stage = acl_stage
        self._media_stage = media_stage

    def collect(self, request: M10SnapshotRequest) -> ConfluenceMaterializedInput:
        if type(request) is not M10SnapshotRequest:
            raise TypeError("invalid request")
        page = _stage_call(self._page_stage, request=request, state={})
        page_documents = _records_from_result(page, ("documents",), "documents")
        source_version = _field(page, "source_version")
        if source_version is None and page_documents:
            source_version = page_documents[0].get("source_version")
        raw_identity = _field(page, "raw_artifact_identity") or request.raw_generation_id
        if type(source_version) is not str or not source_version or type(raw_identity) is not str or not raw_identity:
            raise ValueError("page stage provenance is invalid")
        state: dict[str, object] = {
            "documents": page_documents,
            "chunks": _records_from_result(page, ("chunks",), "chunks"),
            "reference_intents_by_page": _field(page, "reference_intents_by_page") or (),
        }
        relations: tuple[dict[str, object], ...] = _records_from_result(page, ("relations",), "relations") if _field(page, "relations") is not None else ()
        acl: tuple[dict[str, object], ...] = _records_from_result(page, ("acl", "acl_records"), "acl") if _field(page, "acl") is not None or _field(page, "acl_records") is not None else ()
        media: tuple[dict[str, object], ...] = _records_from_result(page, ("media_assets", "assets"), "media_assets") if _field(page, "media_assets") is not None or _field(page, "assets") is not None else ()
        for stage_name, stage in (("relation_stage", self._relation_stage), ("acl_stage", self._acl_stage), ("media_stage", self._media_stage)):
            if stage is None:
                continue
            result = _stage_call(stage, request=request, state=state)
            if stage_name == "relation_stage":
                relations = _records_from_result(result, ("relations", "records"), "relations")
            elif stage_name == "acl_stage":
                acl_value = _field(result, "acl") or _field(result, "acl_records") or _field(result, "acl_record")
                acl = _records(acl_value, "acl") if acl_value is not None else ()
                acl_relations = _field(result, "relations")
                if acl_relations is not None:
                    relations = _merge_records(relations, _records(acl_relations, "relations"), identity="relation_id")
                docs = _field(result, "documents") or _field(result, "enriched_canonical_document")
                chunks = _field(result, "chunks") or _field(result, "enriched_chunks")
                if docs is not None:
                    state["documents"] = _records(docs, "documents")
                if chunks is not None:
                    state["chunks"] = _records(chunks, "chunks")
            else:
                media = _records_from_result(result, ("media_assets", "assets"), "media_assets")
        return ConfluenceMaterializedInput(
            source_version,
            raw_identity,
            state["documents"],
            state["chunks"],
            relations,
            acl,
            media,
        )


class GitM10MaterializedSource:
    """Compose pinned Git document/symbol producers into an M10 source port."""

    def __init__(self, *, document_stage: object, symbol_stage: object | None = None, acl_stage: object | None = None) -> None:
        for name, stage in (("document_stage", document_stage), ("symbol_stage", symbol_stage), ("acl_stage", acl_stage)):
            if stage is not None and not callable(getattr(stage, "execute", None)) and not callable(stage):
                raise TypeError(f"{name} is invalid")
        self._document_stage = document_stage
        self._symbol_stage = symbol_stage
        self._acl_stage = acl_stage

    def collect(self, request: M10SnapshotRequest) -> GitMaterializedInput:
        if type(request) is not M10SnapshotRequest:
            raise TypeError("invalid request")
        result = _stage_call(self._document_stage, request=request, state={})
        state: dict[str, object] = {
            "documents": _records_from_result(result, ("documents",), "documents"),
            "chunks": _records_from_result(result, ("chunks",), "chunks"),
        }
        acl = _records_from_result(result, ("acl", "acl_records"), "acl") if _field(result, "acl") is not None or _field(result, "acl_records") is not None else ()
        symbols = _records_from_result(result, ("symbols", "symbol_records"), "symbols") if _field(result, "symbols") is not None or _field(result, "symbol_records") is not None else ()
        for name, stage in (("symbol_stage", self._symbol_stage), ("acl_stage", self._acl_stage)):
            if stage is None:
                continue
            output = _stage_call(stage, request=request, state=state)
            if name == "symbol_stage":
                symbols = _records_from_result(output, ("symbols", "symbol_records"), "symbols")
                extra_chunks = _field(output, "chunks")
                if extra_chunks is not None:
                    state["chunks"] = _records(extra_chunks, "chunks")
            else:
                acl = _records_from_result(output, ("acl", "acl_records", "records"), "acl")
                docs = _field(output, "documents")
                chunks = _field(output, "chunks")
                if docs is not None:
                    state["documents"] = _records(docs, "documents")
                if chunks is not None:
                    state["chunks"] = _records(chunks, "chunks")
        return GitMaterializedInput(state["documents"], state["chunks"], acl, symbols)


class ConfluenceM10Adapter:
    """Concrete M10 adapter over a trusted, read-only Confluence source port."""

    def __init__(self, *, source: object) -> None:
        if not callable(getattr(source, "collect", None)):
            raise TypeError("Confluence source port is invalid")
        self._source = source

    def collect(self, request: M10SnapshotRequest) -> M10ConfluenceHandoff:
        if type(request) is not M10SnapshotRequest:
            raise M10SourceAdapterError("invalid request")
        try:
            materialized = self._source.collect(request)
            if type(materialized) is not ConfluenceMaterializedInput:
                raise TypeError("invalid materialized input")
            return AssembleConfluenceM10Handoff().execute(
                request=request,
                source_version=materialized.source_version,
                raw_artifact_identity=materialized.raw_artifact_identity,
                documents=materialized.documents,
                chunks=materialized.chunks,
                relations=materialized.relations,
                acl=materialized.acl,
                media_assets=materialized.media_assets,
            )
        except M10SourceAdapterError:
            raise
        except Exception:
            raise M10SourceAdapterError("Confluence collection failed") from None


class GitM10Adapter:
    """Concrete M10 adapter over a trusted, read-only Git source port."""

    def __init__(self, *, source: object) -> None:
        if not callable(getattr(source, "collect", None)):
            raise TypeError("Git source port is invalid")
        self._source = source

    def collect(self, request: M10SnapshotRequest) -> M10GitHandoff:
        if type(request) is not M10SnapshotRequest:
            raise M10SourceAdapterError("invalid request")
        try:
            materialized = self._source.collect(request)
            if type(materialized) is not GitMaterializedInput:
                raise TypeError("invalid materialized input")
            return AssembleGitM10Handoff().execute(
                request=request,
                documents=materialized.documents,
                chunks=materialized.chunks,
                acl=materialized.acl,
                symbols=materialized.symbols,
            )
        except M10SourceAdapterError:
            raise
        except Exception:
            raise M10SourceAdapterError("Git collection failed") from None


__all__ = [
    "ConfluenceM10Adapter",
    "ConfluenceM10MaterializedSource",
    "ConfluenceMaterializedInput",
    "ConfluenceMaterializedSourcePort",
    "GitM10Adapter",
    "GitM10MaterializedSource",
    "GitMaterializedInput",
    "GitMaterializedSourcePort",
    "M10SourceAdapterError",
]
