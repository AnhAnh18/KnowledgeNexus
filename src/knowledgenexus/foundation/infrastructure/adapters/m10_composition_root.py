"""Bounded production composition roots for the M10 source adapters.

The M10 application boundary remains offline and dependency-injected.  These
small roots are the explicit place where an operator binds approved raw-page,
Git, tokenizer, and processor seams to the generic materialized-source
adapters.  They do not read credentials, construct transports, or perform
network calls.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path

from knowledgenexus.foundation.application.use_cases.build_git_code_documents import (
    BuildGitCodeDocuments,
    BuildGitCodeDocumentsRequest,
)
from knowledgenexus.foundation.application.use_cases.build_git_symbols import BuildGitSymbols
from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import (
    ProcessConfluencePageSet,
)
from knowledgenexus.foundation.application.use_cases.build_confluence_jira_relations import BuildConfluenceJiraRelations
from knowledgenexus.foundation.application.use_cases.materialize_confluence_acl import MaterializeConfluenceAcl
from knowledgenexus.foundation.domain.models.confluence_chunking import ChunkingResult
from knowledgenexus.foundation.domain.models.confluence_jira_relations import ConfluenceJiraRelationResult
from knowledgenexus.foundation.domain.records.relation_record_builder import RelationRecordBuilder
from knowledgenexus.foundation.domain.rules.document_id_generator import DocumentIdGenerator
from knowledgenexus.foundation.domain.rules.relation_id_generator import RelationIdGenerator
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageSetRequest,
    ConfluencePageSetResult,
    ConfluencePageWorkItem,
)
from knowledgenexus.foundation.domain.models.git_code_source import (
    GitCasePolicy,
    GitScanBudgets,
    GitSourceConfig,
)
from knowledgenexus.foundation.domain.models.git_code_source import (
    GitCodeBuildResult,
    GitCodeBuildStatus,
)
from knowledgenexus.foundation.domain.models.m10_snapshot import M10SnapshotRequest
from knowledgenexus.foundation.domain.models.symbol_index import (
    BuildGitSymbolsRequest,
    GitSymbolIndexResult,
    GitSymbolIndexStatus,
)
from knowledgenexus.foundation.domain.records.acl_record_builder import ACLRecordBuilder
from knowledgenexus.foundation.infrastructure.adapters.m10_source_adapters import (
    ConfluenceM10Adapter,
    ConfluenceM10MaterializedSource,
    GitM10Adapter,
    GitM10MaterializedSource,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import FoundationSchemaValidator


class M10CompositionRootError(RuntimeError):
    """Sanitized configuration or producer failure at the composition root."""


@dataclass(frozen=True)
class _StageOutput:
    """Small JSON-safe carrier used between approved application seams."""

    documents: tuple[dict[str, object], ...]
    chunks: tuple[dict[str, object], ...]
    source_version: str | None = None
    raw_artifact_identity: str | None = None
    page_references: tuple[object, ...] = ()
    symbols: tuple[dict[str, object], ...] = ()
    acl: tuple[dict[str, object], ...] = ()
    normalized_bodies: tuple[tuple[str, str], ...] = ()


class _ConfluencePageSetStage:
    def __init__(self, processor: object) -> None:
        if not callable(getattr(processor, "execute", None)):
            raise TypeError("page processor is invalid")
        self._processor = processor

    def execute(self, *, request: M10SnapshotRequest) -> _StageOutput:
        if type(request) is not M10SnapshotRequest:
            raise TypeError("invalid request")
        try:
            M10SnapshotRequest.__post_init__(request)
        except Exception:
            raise M10CompositionRootError("invalid request") from None
        try:
            items = tuple(
                ConfluencePageWorkItem(page_id=page_id, crawled_at=request.generated_at)
                for page_id in request.ordered_page_ids
            )
        except Exception:
            raise M10CompositionRootError("Confluence page scope is invalid") from None
        if not items:
            raise M10CompositionRootError("Confluence page scope is empty")
        try:
            page_request = ConfluencePageSetRequest(
                run_id=request.run_id,
                generation_id=request.generation_id,
                items=items,
                profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
            )
        except Exception:
            raise M10CompositionRootError("Confluence page request is invalid") from None
        try:
            result = self._processor.execute(request=page_request)
        except Exception:
            raise M10CompositionRootError("Confluence page processing failed") from None
        if type(result) is not ConfluencePageSetResult:
            raise M10CompositionRootError("Confluence page result is invalid")
        documents = tuple(copy.deepcopy(result.documents))
        chunks = tuple(copy.deepcopy(result.chunks))
        versions: set[str] = set()
        for record in documents:
            version = record.get("source_version")
            if type(version) is not str or not version:
                raise M10CompositionRootError("Confluence source version is invalid")
            versions.add(version)
        source_version = next(iter(versions)) if len(versions) == 1 else "mixed"
        normalized: list[tuple[str, str]] = []
        # The approved relation producer needs the exact normalized body. The
        # page-set result intentionally omits it, so recover it through the
        # same processor seams (never by reparsing raw JSON here).
        read_envelope = getattr(self._processor, "_read_envelope", None)
        normalize = getattr(self._processor, "_normalize", None)
        if callable(read_envelope) and callable(normalize):
            for item in items:
                envelope = read_envelope(request=page_request, item=item)
                content = normalize(item=item, envelope=envelope)
                normalized.append((item.page_id, content.normalized_body_text))
        return _StageOutput(
            documents=documents,
            chunks=chunks,
            source_version=source_version,
            raw_artifact_identity=request.raw_generation_id,
            page_references=tuple(result.reference_intents_by_page),
            normalized_bodies=tuple(normalized),
        )


class _ConfluenceAclRelationStage:
    """Drive Jira relation extraction and deny-safe ACL through approved use cases."""

    def __init__(self, *, validator: object) -> None:
        if not callable(getattr(validator, "validate_record", None)):
            raise TypeError("schema validator is invalid")
        self._validator = validator

    def execute(self, *, request: M10SnapshotRequest, documents: object, chunks: object, normalized_bodies: object = (), **_: object) -> dict[str, object]:
        if type(request) is not M10SnapshotRequest or type(documents) is not tuple or type(chunks) is not tuple or type(normalized_bodies) is not tuple:
            raise TypeError("invalid ACL stage input")
        bodies = dict(normalized_bodies)
        by_document: dict[str, list[dict[str, object]]] = {}
        for chunk in chunks:
            if type(chunk) is not dict or type(chunk.get("document_id")) is not str:
                raise TypeError("invalid chunk")
            by_document.setdefault(chunk["document_id"], []).append(copy.deepcopy(chunk))
        relation_builder = BuildConfluenceJiraRelations(
            profile=request.profile_bundle.jira_relation_profile,
            document_id_generator=DocumentIdGenerator,
            relation_id_generator=RelationIdGenerator,
            relation_record_builder=RelationRecordBuilder,
            schema_validator=self._validator,
        )
        acl_builder = MaterializeConfluenceAcl(schema_validator=self._validator)
        output_docs: list[dict[str, object]] = []
        output_chunks: list[dict[str, object]] = []
        acl_rows: list[dict[str, object]] = []
        relations: list[dict[str, object]] = []
        for document in documents:
            if type(document) is not dict:
                raise TypeError("invalid document")
            document_id = document.get("document_id")
            page_id = document.get("page_id")
            if type(document_id) is not str or type(page_id) is not str or page_id not in bodies:
                raise ValueError("normalized page body is missing")
            doc_chunks = tuple(by_document.get(document_id, ()))
            chunking = ChunkingResult(records=doc_chunks, metrics={"chunks_total": len(doc_chunks), "chunks_over_hard_max": 0})
            jira = relation_builder.execute(
                normalized_body_text=bodies[page_id],
                canonical_document=document,
                chunking_result=chunking,
                created_at=request.generated_at,
            )
            observation = ({"source_page_id": page_id, "http_status": 404, "classification": "unavailable", "users": [], "groups": []},)
            acl = acl_builder.execute(
                jira_relation_result=jira,
                restriction_observations=observation,
                crawler_identity="m10-offline-replay",
                extracted_at=request.generated_at,
            )
            output_docs.append(acl.enriched_canonical_document)
            output_chunks.extend(acl.enriched_chunks)
            acl_rows.append(acl.acl_record)
            relations.extend(jira.relations)
        return {"documents": tuple(output_docs), "chunks": tuple(output_chunks), "acl": tuple(acl_rows), "relations": tuple(relations)}


class ConfluenceM10CompositionRoot:
    """Bind approved Confluence seams into a concrete ``ConfluenceM10Adapter``.

    ``relation_stage``, ``acl_stage``, and ``media_stage`` are already-built
    application seams.  Keeping them as constructor inputs makes this root
    usable for both the production transport harness and offline replay while
    ensuring the adapter never receives credentials or filesystem paths from an
    M10 request.
    """

    @classmethod
    def build(
        cls,
        *,
        raw_page_store: object,
        tokenizer: object,
        chunking_profile: object,
        raw_page_mapper: object,
        storage_normalizer: object,
        relation_stage: object | None = None,
        acl_stage: object | None = None,
        media_stage: object | None = None,
        tombstone_stage: object | None = None,
        sync_inventory_stage: object | None = None,
        schema_validator: object | None = None,
    ) -> ConfluenceM10Adapter:
        """Construct the read-only adapter from configured approved seams."""
        validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
        if not callable(getattr(validator, "validate_record", None)):
            raise TypeError("schema validator is invalid")
        try:
            processor = ProcessConfluencePageSet(
                chunking_profile=chunking_profile,
                tokenizer=tokenizer,
                raw_page_store=raw_page_store,
                raw_page_mapper=raw_page_mapper,
                storage_normalizer=storage_normalizer,
                schema_validator=validator,
            )
            # Never publish a silently incomplete M10 handoff. These stages
            # must be explicitly composed by the operator/application profile.
            if relation_stage is None or media_stage is None:
                raise M10CompositionRootError("Confluence relation/media stages are not configured")
            if acl_stage is None:
                acl_stage = _ConfluenceAclRelationStage(validator=validator)
            source = ConfluenceM10MaterializedSource(
                page_stage=_ConfluencePageSetStage(processor),
                relation_stage=relation_stage,
                acl_stage=acl_stage,
                media_stage=media_stage,
                tombstone_stage=tombstone_stage,
                inventory_stage=sync_inventory_stage,
            )
            return ConfluenceM10Adapter(source=source)
        except M10CompositionRootError:
            raise
        except (TypeError, ValueError):
            raise
        except Exception:
            raise M10CompositionRootError("Confluence composition failed") from None


class _GitApprovedStage:
    def __init__(
        self,
        *,
        repository_reader: object,
        tokenizer: object,
        repository_root: Path,
        budgets: GitScanBudgets,
        case_policy: GitCasePolicy,
        schema_validator: object,
        symbol_parser: object | None,
    ) -> None:
        if not callable(getattr(repository_reader, "read", None)):
            raise TypeError("Git repository reader is invalid")
        if not callable(getattr(tokenizer, "tokenize", None)):
            raise TypeError("Git tokenizer is invalid")
        if (
            not isinstance(repository_root, Path)
            or not repository_root.is_absolute()
            or not repository_root.exists()
            or not repository_root.is_dir()
            or repository_root.is_symlink()
        ):
            raise TypeError("Git repository root is invalid")
        if type(budgets) is not GitScanBudgets or type(case_policy) is not GitCasePolicy:
            raise TypeError("Git scan configuration is invalid")
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema validator is invalid")
        if symbol_parser is not None and not callable(getattr(symbol_parser, "parse", None)):
            raise TypeError("Git symbol parser is invalid")
        self._reader = repository_reader
        self._tokenizer = tokenizer
        self._repository_root = repository_root
        self._budgets = budgets
        self._case_policy = case_policy
        self._validator = schema_validator
        self._symbol_parser = symbol_parser

    def execute(self, *, request: M10SnapshotRequest) -> _StageOutput:
        if type(request) is not M10SnapshotRequest:
            raise TypeError("invalid request")
        try:
            M10SnapshotRequest.__post_init__(request)
        except Exception:
            raise M10CompositionRootError("invalid request") from None
        try:
            config = GitSourceConfig(
                clone_root=self._repository_root,
                repo_name=request.git_repository,
                branch=request.git_branch,
                commit_sha=request.git_commit,
                crawled_at=request.generated_at,
                budgets=self._budgets,
                case_policy=self._case_policy,
            )
        except Exception:
            raise M10CompositionRootError("Git source configuration is invalid") from None
        result = BuildGitCodeDocuments(
            repository_reader=self._reader,
            tokenizer=self._tokenizer,
            schema_validator=self._validator,
        ).execute(
            BuildGitCodeDocumentsRequest(
                config=config,
                chunking_profile=request.profile_bundle.chunking_profile,
            )
        )
        if type(result) is not GitCodeBuildResult or result.status is not GitCodeBuildStatus.SUCCESS or result.plan is None:
            raise M10CompositionRootError("Git document processing failed")
        plan = result.plan
        symbols: tuple[dict[str, object], ...] = ()
        chunks = tuple(copy.deepcopy(plan.chunks))
        if self._symbol_parser is not None:
            symbol_result = BuildGitSymbols(
                parser=self._symbol_parser,
                tokenizer=self._tokenizer,
                schema_validator=self._validator,
            ).execute(
                BuildGitSymbolsRequest(
                    plan=plan,
                    chunking_profile=request.profile_bundle.chunking_profile,
                    scanned_at=request.generated_at,
                )
            )
            if type(symbol_result) is not GitSymbolIndexResult or symbol_result.status is not GitSymbolIndexStatus.SUCCESS:
                raise M10CompositionRootError("Git symbol processing failed")
            symbols = tuple(copy.deepcopy(symbol_result.symbol_records))
            chunks = tuple(copy.deepcopy(symbol_result.chunks))
        document_rows = [copy.deepcopy(document) for document in plan.documents]
        acl_ids = [document.get("acl_id") for document in document_rows]
        if len(set(acl_ids)) != len(acl_ids):
            # The Git producer historically used one repository ACL ID for
            # every file. M10 emits one ACL row per document, so derive stable
            # per-file IDs only when that legacy shape would collide.
            for document in document_rows:
                document_id = str(document["document_id"])
                suffix = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:16]
                document["acl_id"] = f"acl:repo:{request.git_repository}:{suffix}"
        acl = tuple(
            ACLRecordBuilder.build(
                acl_id=str(document["acl_id"]),
                document_id=str(document["document_id"]),
                source_system="git",
                is_restricted=False,
                acl_tags=[f"repo:{request.git_repository}"],
                acl_extraction_status="ok",
                extracted_at=request.generated_at,
            )
            for document in document_rows
        )
        return _StageOutput(
            documents=tuple(document_rows),
            chunks=chunks,
            symbols=symbols,
            acl=acl,
        )


class GitM10CompositionRoot:
    """Bind a pinned Git reader and approved processors to ``GitM10Adapter``."""

    @classmethod
    def build(
        cls,
        *,
        repository_reader: object,
        tokenizer: object,
        repository_root: Path,
        budgets: GitScanBudgets,
        case_policy: GitCasePolicy,
        symbol_parser: object | None = None,
        sync_inventory_stage: object | None = None,
        schema_validator: object | None = None,
    ) -> GitM10Adapter:
        validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
        stage = _GitApprovedStage(
            repository_reader=repository_reader,
            tokenizer=tokenizer,
            repository_root=repository_root,
            budgets=budgets,
            case_policy=case_policy,
            schema_validator=validator,
            symbol_parser=symbol_parser,
        )
        return GitM10Adapter(
            source=GitM10MaterializedSource(
                document_stage=stage,
                inventory_stage=sync_inventory_stage,
            )
        )


__all__ = [
    "ConfluenceM10CompositionRoot",
    "GitM10CompositionRoot",
    "M10CompositionRootError",
]
