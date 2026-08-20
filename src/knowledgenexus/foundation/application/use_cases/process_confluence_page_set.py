from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from knowledgenexus.foundation.application.use_cases.build_confluence_chunks import (
    BuildConfluenceChunks,
)
from knowledgenexus.foundation.application.use_cases.normalize_confluence_page import (
    ConfluencePageNormalizationError,
    NormalizeConfluencePage,
)
from knowledgenexus.foundation.application.use_cases.parse_wiki_document_structure import (
    parse_wiki_document_structure,
)
from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.confluence_chunking import (
    ChunkingResult,
    ConfluenceChunkingError,
)
from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluencePageNormalizationResult,
    NormalizationReferenceIntent,
)
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageSetError,
    ConfluencePageSetFailureCategory,
    ConfluencePageSetMetrics,
    ConfluencePageSetPageMetrics,
    ConfluencePageSetRequest,
    ConfluencePageSetResult,
    ConfluencePageWorkItem,
    validate_raw_page_envelope,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiDocumentStructure,
)
from knowledgenexus.foundation.domain.rules.chunk_id_generator import ChunkIdGenerator
from knowledgenexus.foundation.domain.records.chunk_record_builder import (
    ChunkRecordBuilder,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceRawPageMapperPort,
    ConfluenceStorageNormalizerPort,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStorePort,
)
from knowledgenexus.foundation.ports.raw_page_observation_store_port import (
    RawPageReadError,
    RawPageReadPort,
)
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerPort
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


class _ChunkIdGeneratorPort(Protocol):
    @staticmethod
    def generate_chunk_id(
        source_system: str,
        document_stable_key: str,
        unit_key: str,
        normalized_text: str,
    ) -> str: ...


class _ChunkRecordBuilderPort(Protocol):
    @classmethod
    def build(cls, **fields: object) -> dict[str, object]: ...


class _FixedRawPageReader(RawPageReadPort):
    def __init__(self, *, page_id: str, body_bytes: bytes) -> None:
        if type(page_id) is not str or type(body_bytes) is not bytes:
            raise TypeError("fixed raw page reader input is invalid")
        self._page_id = page_id
        self._body_bytes = bytes(body_bytes)

    def read_page(self, *, page_id: str) -> bytes:
        if page_id != self._page_id:
            raise RawPageReadError("raw page identity does not match")
        return self._body_bytes


def _profile_identity(profile: ChunkingProfile) -> str:
    expected_values = {
        "chunker_version": "1.3.0",
        "profile_status": "provisional_until_benchmark",
        "active_profile": "medium",
        "model_name": "BAAI/bge-m3",
        "tokenizer_name": "BAAI/bge-m3",
        "tokenizer_family": "SentencePiece / XLM-R",
        "vector_dimension": 1024,
        "maximum_model_tokens": 8192,
        "target_tokens": 450,
        "minimum_tokens": 96,
        "hard_maximum_tokens": 1000,
        "overlap_tokens": 64,
        "code_window_target_tokens": 450,
        "code_window_max_lines": 40,
        "code_window_overlap_lines": 4,
        "tokenizer_repository": "https://huggingface.co/BAAI/bge-m3",
        "tokenizer_revision": "5617a9f61b028005a4858fdac845db406aefb181",
        "observed_license": "MIT",
        "transformers_version": "4.57.6",
        "tokenizers_version": "0.22.2",
        "sentencepiece_version": "0.2.2",
    }
    for name, expected in expected_values.items():
        actual = getattr(profile, name)
        if type(expected) is str and type(actual) is not str:
            raise ValueError("chunker profile identity is invalid")
        if type(expected) is int and type(actual) is not int:
            raise ValueError("chunker profile identity is invalid")
        if actual != expected:
            raise ValueError("chunker profile identity is invalid")
    expected_provenance = (
        "https://huggingface.co/BAAI/bge-m3/tree/"
        "5617a9f61b028005a4858fdac845db406aefb181"
    )
    if type(profile.provenance_url) is not str or profile.provenance_url != expected_provenance:
        raise ValueError("chunker profile identity is invalid")
    if type(profile.tokenizer_assets) is not tuple or len(profile.tokenizer_assets) != 1:
        raise ValueError("chunker profile identity is invalid")
    asset = profile.tokenizer_assets[0]
    if (
        type(asset.filename) is not str
        or asset.filename != "tokenizer.json"
        or type(asset.byte_size) is not int
        or asset.byte_size != 17098108
        or type(asset.sha256) is not str
        or asset.sha256
        != "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08"
    ):
        raise ValueError("chunker profile identity is invalid")
    return ACTIVE_PAGE_SET_PROFILE_IDENTITY


class ProcessConfluencePageSet:
    """Read, normalize, parse, and chunk one immutable raw-page generation set."""

    def __init__(
        self,
        *,
        chunking_profile: ChunkingProfile,
        tokenizer: TokenizerPort,
        raw_page_store: ConfluenceRawPageStorePort,
        raw_page_mapper: ConfluenceRawPageMapperPort,
        storage_normalizer: ConfluenceStorageNormalizerPort,
        schema_validator: object | None = None,
        chunk_id_generator: _ChunkIdGeneratorPort = ChunkIdGenerator,
        chunk_record_builder: _ChunkRecordBuilderPort = ChunkRecordBuilder,
    ) -> None:
        if type(chunking_profile) is not ChunkingProfile:
            raise TypeError("chunking_profile is invalid")
        self._profile_identity = _profile_identity(chunking_profile)
        if not callable(getattr(tokenizer, "tokenize", None)):
            raise TypeError("tokenizer is invalid")
        if not callable(getattr(raw_page_store, "read_page", None)):
            raise TypeError("raw_page_store is invalid")
        if not callable(getattr(raw_page_mapper, "map_page", None)):
            raise TypeError("raw_page_mapper is invalid")
        if not callable(getattr(storage_normalizer, "normalize", None)):
            raise TypeError("storage_normalizer is invalid")
        if not callable(getattr(chunk_id_generator, "generate_chunk_id", None)):
            raise TypeError("chunk_id_generator is invalid")
        if not callable(getattr(chunk_record_builder, "build", None)):
            raise TypeError("chunk_record_builder is invalid")
        if schema_validator is None:
            schema_validator = FoundationSchemaValidator()
        if not callable(getattr(schema_validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        self._profile = chunking_profile
        self._tokenizer = tokenizer
        self._raw_page_store = raw_page_store
        self._raw_page_mapper = raw_page_mapper
        self._storage_normalizer = storage_normalizer
        self._schema_validator = schema_validator
        self._chunk_id_generator = chunk_id_generator
        self._chunk_record_builder = chunk_record_builder

    def execute(self, *, request: ConfluencePageSetRequest) -> ConfluencePageSetResult:
        if type(request) is not ConfluencePageSetRequest:
            raise ConfluencePageSetError(
                ConfluencePageSetFailureCategory.INVALID_REQUEST,
                page_ordinal=0,
                requested_pages=0,
                succeeded_pages=0,
            )
        if (
            type(request.run_id) is not CrawlRunId
            or type(request.generation_id) is not CrawlRunId
            or request.run_id != request.generation_id
            or type(request.items) is not tuple
            or not request.items
            or any(type(item) is not ConfluencePageWorkItem for item in request.items)
        ):
            raise ConfluencePageSetError(
                ConfluencePageSetFailureCategory.INVALID_REQUEST,
                page_ordinal=0,
                requested_pages=0,
                succeeded_pages=0,
            )
        try:
            validated_items = tuple(
                ConfluencePageWorkItem(
                    page_id=item.page_id,
                    crawled_at=item.crawled_at,
                    expected_source_version=item.expected_source_version,
                )
                for item in request.items
            )
        except (TypeError, ValueError):
            validated_items = ()
        page_ids = tuple(item.page_id for item in validated_items)
        if (
            len(validated_items) != len(request.items)
            or any(type(page_id) is not str for page_id in page_ids)
            or len(set(page_ids)) != len(page_ids)
        ):
            raise ConfluencePageSetError(
                ConfluencePageSetFailureCategory.INVALID_REQUEST,
                page_ordinal=0,
                requested_pages=0,
                succeeded_pages=0,
            )
        request = ConfluencePageSetRequest(
            run_id=request.run_id,
            generation_id=request.generation_id,
            items=validated_items,
            profile_identity=request.profile_identity,
        )
        if (
            type(request.profile_identity) is not str
            or request.profile_identity != self._profile_identity
        ):
            raise ConfluencePageSetError(
                ConfluencePageSetFailureCategory.INVALID_REQUEST,
                page_ordinal=0,
                requested_pages=len(request.items),
                succeeded_pages=0,
            )

        documents: list[dict[str, object]] = []
        chunks: list[dict[str, object]] = []
        page_metrics: list[ConfluencePageSetPageMetrics] = []
        reference_intents_by_page: list[
            tuple[str, tuple[NormalizationReferenceIntent, ...]]
        ] = []
        kind_totals: Counter[str] = Counter()
        warning_total = 0
        intent_total = 0

        for ordinal, item in enumerate(request.items, start=1):
            try:
                envelope = self._read_envelope(request=request, item=item)
                normalization = self._normalize(
                    item=item,
                    envelope=envelope,
                )
                if type(normalization) is not ConfluencePageNormalizationResult:
                    raise TypeError("normalization result is invalid")
                self._validate_source_versions(
                    item=item,
                    envelope=envelope,
                    normalization=normalization,
                )
                try:
                    structure = parse_wiki_document_structure(normalization)
                except Exception as exc:
                    raise _StageFailure(
                        ConfluencePageSetFailureCategory.STRUCTURE_FAILED
                    ) from exc
                if type(structure) is not WikiDocumentStructure:
                    raise _StageFailure(
                        ConfluencePageSetFailureCategory.STRUCTURE_FAILED
                    )
                try:
                    chunking = BuildConfluenceChunks(
                        profile=self._profile,
                        tokenizer=self._tokenizer,
                        chunk_id_generator=self._chunk_id_generator,
                        chunk_record_builder=self._chunk_record_builder,
                        schema_validator=self._schema_validator,
                    ).execute(
                        canonical_document=normalization.canonical_document,
                        structure=structure,
                    )
                except ConfluenceChunkingError as exc:
                    raise _StageFailure(
                        ConfluencePageSetFailureCategory.CHUNKING_FAILED
                    ) from exc
                except Exception as exc:
                    raise _StageFailure(
                        ConfluencePageSetFailureCategory.CHUNKING_FAILED
                    ) from exc
                if type(chunking) is not ChunkingResult:
                    raise _StageFailure(
                        ConfluencePageSetFailureCategory.CHUNKING_FAILED
                    )
                page_chunks = [dict(record) for record in chunking.records]
                content_kinds = Counter(
                    record.get("content_kind")
                    for record in page_chunks
                    if isinstance(record.get("content_kind"), str)
                )
                if sum(content_kinds.values()) != len(page_chunks):
                    raise _StageFailure(
                        ConfluencePageSetFailureCategory.CHUNKING_FAILED
                    )
                page_metric = ConfluencePageSetPageMetrics(
                    page_ordinal=ordinal,
                    chunk_count=len(page_chunks),
                    warning_count=len(normalization.warnings),
                    reference_intent_count=len(normalization.reference_intents),
                    content_kind_counts=tuple(sorted(content_kinds.items())),
                )
                documents.append(dict(normalization.canonical_document))
                chunks.extend(page_chunks)
                reference_intents_by_page.append(
                    (
                        str(normalization.canonical_document["document_id"]),
                        tuple(normalization.reference_intents),
                    )
                )
                page_metrics.append(page_metric)
                for kind, count in content_kinds.items():
                    kind_totals[kind] += count
                warning_total += page_metric.warning_count
                intent_total += page_metric.reference_intent_count
            except _StageFailure as failure:
                raise self._error(
                    failure.category,
                    ordinal=ordinal,
                    requested=len(request.items),
                    succeeded=len(documents),
                ) from None
            except ConfluencePageSetError:
                raise
            except Exception as exc:
                category = ConfluencePageSetFailureCategory.INTERNAL_FAILURE
                if isinstance(exc, ConfluencePageNormalizationError):
                    category = ConfluencePageSetFailureCategory.NORMALIZATION_FAILED
                raise self._error(
                    category,
                    ordinal=ordinal,
                    requested=len(request.items),
                    succeeded=len(documents),
                ) from None

        metrics = ConfluencePageSetMetrics(
            requested_pages=len(request.items),
            succeeded_pages=len(documents),
            failed_pages=0,
            document_count=len(documents),
            chunk_count=len(chunks),
            warning_count=warning_total,
            reference_intent_count=intent_total,
            content_kind_counts=tuple(sorted(kind_totals.items())),
        )
        try:
            return ConfluencePageSetResult(
                documents=tuple(documents),
                chunks=tuple(chunks),
                page_metrics=tuple(page_metrics),
                metrics=metrics,
                reference_intents_by_page=tuple(reference_intents_by_page),
            )
        except (TypeError, ValueError):
            raise self._error(
                ConfluencePageSetFailureCategory.CHUNKING_FAILED,
                ordinal=len(request.items),
                requested=len(request.items),
                succeeded=len(documents),
            ) from None

    def _read_envelope(
        self,
        *,
        request: ConfluencePageSetRequest,
        item: ConfluencePageWorkItem,
    ) -> ConfluenceRawPageEnvelope:
        try:
            envelope = self._raw_page_store.read_page(
                run_id=request.run_id,
                page_id=item.page_id,
            )
        except Exception as exc:
            raise _StageFailure(
                ConfluencePageSetFailureCategory.RAW_PAGE_READ_FAILED
            ) from exc
        if type(envelope) is not ConfluenceRawPageEnvelope:
            raise _StageFailure(
                ConfluencePageSetFailureCategory.RAW_PAGE_ENVELOPE_INVALID
            )
        if envelope.http_status != 200:
            raise _StageFailure(
                ConfluencePageSetFailureCategory.RAW_PAGE_STATUS_FAILED
            )
        if (
            item.expected_source_version is not None
            and envelope.source_version != item.expected_source_version
        ):
            raise _StageFailure(
                ConfluencePageSetFailureCategory.SOURCE_VERSION_MISMATCH
            )
        try:
            return validate_raw_page_envelope(
                envelope,
                request=request,
                item=item,
            )
        except Exception as exc:
            raise _StageFailure(
                ConfluencePageSetFailureCategory.RAW_PAGE_ENVELOPE_INVALID
            ) from exc

    def _normalize(
        self,
        *,
        item: ConfluencePageWorkItem,
        envelope: ConfluenceRawPageEnvelope,
    ) -> ConfluencePageNormalizationResult:
        try:
            return NormalizeConfluencePage(
                raw_page_reader=_FixedRawPageReader(
                    page_id=item.page_id,
                    body_bytes=envelope.body_bytes,
                ),
                raw_page_mapper=self._raw_page_mapper,
                storage_normalizer=self._storage_normalizer,
            ).execute(
                page_id=item.page_id,
                crawled_at=item.crawled_at,
            )
        except ConfluencePageNormalizationError:
            raise
        except Exception as exc:
            raise ConfluencePageNormalizationError("normalization_failed") from exc

    @staticmethod
    def _validate_source_versions(
        *,
        item: ConfluencePageWorkItem,
        envelope: ConfluenceRawPageEnvelope,
        normalization: ConfluencePageNormalizationResult,
    ) -> None:
        if type(normalization.canonical_document.get("page_id")) is not str:
            raise _StageFailure(
                ConfluencePageSetFailureCategory.DOCUMENT_IDENTITY_MISMATCH
            )
        if normalization.canonical_document.get("page_id") != item.page_id:
            raise _StageFailure(
                ConfluencePageSetFailureCategory.DOCUMENT_IDENTITY_MISMATCH
            )
        canonical_version = normalization.canonical_document.get("source_version")
        if (
            type(canonical_version) is not str
            or type(envelope.source_version) is not str
            or envelope.source_version != canonical_version
        ):
            raise _StageFailure(ConfluencePageSetFailureCategory.SOURCE_VERSION_MISMATCH)
        if (
            item.expected_source_version is not None
            and item.expected_source_version != canonical_version
        ):
            raise _StageFailure(ConfluencePageSetFailureCategory.SOURCE_VERSION_MISMATCH)

    @staticmethod
    def _error(
        category: ConfluencePageSetFailureCategory,
        *,
        ordinal: int,
        requested: int,
        succeeded: int,
    ) -> ConfluencePageSetError:
        return ConfluencePageSetError(
            category,
            page_ordinal=ordinal,
            requested_pages=requested,
            succeeded_pages=succeeded,
        )


@dataclass(frozen=True)
class _StageFailure(Exception):
    category: ConfluencePageSetFailureCategory
