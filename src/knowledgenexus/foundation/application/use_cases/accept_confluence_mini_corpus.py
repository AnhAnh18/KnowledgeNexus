from __future__ import annotations

import hashlib
import copy
import json
import math
import re
import time
from collections.abc import Callable

from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import (
    ProcessConfluencePageSet,
)
from knowledgenexus.foundation.domain.models.chunk_stability import (
    DocumentChunkSetSummary,
)
from knowledgenexus.foundation.domain.models.confluence_mini_corpus_acceptance import (
    MiniCorpusAcceptanceError,
    MiniCorpusAcceptanceFailureCategory,
    MiniCorpusAcceptanceRequest,
    MiniCorpusAcceptanceSummary,
)
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ConfluencePageSetError,
    ConfluencePageSetRequest,
    ConfluencePageSetResult,
)
from knowledgenexus.foundation.domain.models.chunk_stability import ACTIVE_CHUNKER_VERSION
from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.domain.models.wiki_document_structure import (
    WikiDocumentStructure,
)
from knowledgenexus.foundation.domain.rules.chunk_stability_builder import (
    ChunkStabilitySummaryBuilder,
)
from knowledgenexus.foundation.ports.confluence_page_normalization_port import (
    ConfluenceStorageNormalizationError,
    ConfluenceStorageNormalizerPort,
)
from knowledgenexus.foundation.ports.confluence_raw_page_store_port import (
    ConfluenceRawPageStorePort,
)
from knowledgenexus.foundation.ports.tokenizer_port import TokenizerPort
from knowledgenexus.foundation.domain.models.confluence_page_content import (
    ConfluenceStorageNormalization,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


_LAYOUT_TAG = re.compile(r"<(?:(?:[A-Za-z_][\w.-]*):)?layout(?:[-\s>])", re.IGNORECASE)
_ZERO_DIGEST = "0" * 64


class _CoverageNormalizer(ConfluenceStorageNormalizerPort):
    def __init__(self, delegate: ConfluenceStorageNormalizerPort) -> None:
        if not callable(getattr(delegate, "normalize", None)):
            raise TypeError("normalizer is invalid")
        self._delegate = delegate
        self.layout_pages = 0

    def normalize(self, *, storage_xhtml: str) -> ConfluenceStorageNormalization:
        if type(storage_xhtml) is not str:
            raise TypeError("storage XHTML is invalid")
        if _LAYOUT_TAG.search(storage_xhtml):
            self.layout_pages += 1
        result = self._delegate.normalize(storage_xhtml=storage_xhtml)
        if type(result) is not ConfluenceStorageNormalization:
            raise TypeError("normalization result is invalid")
        return result


class _CorruptEnvelopeStore(ConfluenceRawPageStorePort):
    def __init__(self, delegate: ConfluenceRawPageStorePort) -> None:
        self._delegate = delegate
        self._first = True

    def read_page(self, *, run_id, page_id):
        if self._first:
            self._first = False
            return object()
        return self._delegate.read_page(run_id=run_id, page_id=page_id)


class _FailingNormalizer(ConfluenceStorageNormalizerPort):
    def __init__(self, delegate: ConfluenceStorageNormalizerPort) -> None:
        self._delegate = delegate
        self._first = True

    def normalize(self, *, storage_xhtml: str) -> ConfluenceStorageNormalization:
        if self._first:
            self._first = False
            raise ConfluenceStorageNormalizationError("normalization failed")
        return self._delegate.normalize(storage_xhtml=storage_xhtml)


class _WrongGenerationStore(ConfluenceRawPageStorePort):
    def __init__(self, delegate: ConfluenceRawPageStorePort, generation_id) -> None:
        self._delegate = delegate
        self._generation_id = generation_id

    def read_page(self, *, run_id, page_id):
        envelope = self._delegate.read_page(run_id=run_id, page_id=page_id)
        altered = copy.copy(envelope)
        object.__setattr__(altered, "generation_id", self._generation_id)
        return altered


class AcceptConfluenceMiniCorpus:
    """Run two aggregate-only passes over a bounded immutable page selection."""

    def __init__(
        self,
        *,
        chunking_profile: object,
        tokenizer: TokenizerPort,
        raw_page_store_factory: Callable[[], ConfluenceRawPageStorePort],
        raw_page_mapper: object,
        storage_normalizer: ConfluenceStorageNormalizerPort,
        schema_validator: object | None = None,
        source_fingerprint: Callable[[], str] | None = None,
        write_fingerprint: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(chunking_profile, ChunkingProfile):
            raise TypeError("chunking profile is invalid")
        if not callable(getattr(tokenizer, "tokenize", None)):
            raise TypeError("tokenizer is invalid")
        if not callable(raw_page_store_factory):
            raise TypeError("raw_page_store_factory is invalid")
        if not callable(getattr(raw_page_mapper, "map_page", None)):
            raise TypeError("raw_page_mapper is invalid")
        if not callable(getattr(storage_normalizer, "normalize", None)):
            raise TypeError("storage_normalizer is invalid")
        validator = FoundationSchemaValidator() if schema_validator is None else schema_validator
        if not callable(getattr(validator, "validate_record", None)):
            raise TypeError("schema_validator is invalid")
        if source_fingerprint is not None and not callable(source_fingerprint):
            raise TypeError("source_fingerprint is invalid")
        if write_fingerprint is None or not callable(write_fingerprint):
            raise TypeError("write_fingerprint is invalid")
        self._profile = chunking_profile
        self._tokenizer = tokenizer
        self._store_factory = raw_page_store_factory
        self._mapper = raw_page_mapper
        self._normalizer = storage_normalizer
        self._validator = validator
        self._source_fingerprint = source_fingerprint
        self._write_fingerprint = write_fingerprint

    def execute(self, *, request: object) -> MiniCorpusAcceptanceSummary:
        if type(request) is not MiniCorpusAcceptanceRequest:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.INVALID_INPUT)
        before = self._fingerprint()
        before_writes = self._write_fingerprint_value()
        started = time.perf_counter()
        first = self._run_pass(request)
        second = self._run_pass(request)
        after = self._fingerprint()
        after_writes = self._write_fingerprint_value()
        first_page_bytes = first[0].to_canonical_json()
        second_page_bytes = second[0].to_canonical_json()
        first_summary_bytes = self._summary_bytes(first[1])
        second_summary_bytes = self._summary_bytes(second[1])
        if first_page_bytes != second_page_bytes or first_summary_bytes != second_summary_bytes:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.NONDETERMINISTIC)
        source_unchanged = before == after
        no_writes = before_writes == after_writes
        if not source_unchanged:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.MUTATION_DETECTED)
        if not no_writes:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.MUTATION_DETECTED)
        negative_pass = self._negative_pass(request)
        if not negative_pass:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.NEGATIVE_PROBE_FAILED)
        page_result, summaries, coverage = first
        result_bytes = first_page_bytes
        summary_bytes = first_summary_bytes
        summary = self._summary(
            request=request,
            result=page_result,
            summaries=summaries,
            coverage=coverage,
            page_set_digest=hashlib.sha256(result_bytes).hexdigest(),
            chunk_stability_digest=hashlib.sha256(summary_bytes).hexdigest(),
            first_page_set_digest=hashlib.sha256(first_page_bytes).hexdigest(),
            second_page_set_digest=hashlib.sha256(second_page_bytes).hexdigest(),
            first_chunk_stability_digest=hashlib.sha256(first_summary_bytes).hexdigest(),
            second_chunk_stability_digest=hashlib.sha256(second_summary_bytes).hexdigest(),
            tokenizer_asset_digest=self._tokenizer_asset_digest(),
            deterministic_repeat=True,
            source_unchanged=source_unchanged,
            no_writes=no_writes,
            negative_pass=True,
            duration_milliseconds=max(0, int((time.perf_counter() - started) * 1000)),
        )
        if not self._report_is_leak_free(summary.to_bytes()):
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.REPORT_INVALID)
        return summary

    def _run_pass(
        self, request: MiniCorpusAcceptanceRequest, *, normalizer: object | None = None,
        store: ConfluenceRawPageStorePort | None = None, preserve_errors: bool = False,
    ) -> tuple[ConfluencePageSetResult, tuple[DocumentChunkSetSummary, ...], dict[str, int]]:
        selected_store = self._store_factory() if store is None else store
        if not callable(getattr(selected_store, "read_page", None)):
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.SOURCE_INVALID)
        coverage_normalizer = _CoverageNormalizer(self._normalizer if normalizer is None else normalizer)
        page_request = ConfluencePageSetRequest(
            run_id=request.run_id,
            generation_id=request.generation_id,
            items=request.items,
            profile_identity=request.profile_identity,
        )
        try:
            result = ProcessConfluencePageSet(
                chunking_profile=self._profile,
                tokenizer=self._tokenizer,
                raw_page_store=selected_store,
                raw_page_mapper=self._mapper,
                storage_normalizer=coverage_normalizer,
                schema_validator=self._validator,
            ).execute(request=page_request)
            summaries = ChunkStabilitySummaryBuilder.build_page_set(
                result=result,
                schema_validator=self._validator,
            )
        except ConfluencePageSetError as exc:
            if preserve_errors:
                raise
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.PROCESSING_FAILED) from exc
        except Exception as exc:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.PROCESSING_FAILED) from exc
        coverage = {
            "layout_page_count": coverage_normalizer.layout_pages,
            "table_page_count": self._table_pages(result),
            "reference_page_count": sum(1 for item in result.page_metrics if item.reference_intent_count > 0),
        }
        return result, summaries, coverage

    def _negative_pass(self, request: MiniCorpusAcceptanceRequest) -> bool:
        duplicate_items = request.items[:-1] + (request.items[0],)
        try:
            MiniCorpusAcceptanceRequest(
                run_id=request.run_id,
                generation_id=request.generation_id,
                items=duplicate_items,
                profile_identity=request.profile_identity,
            )
        except (TypeError, ValueError):
            pass
        else:
            return False
        alternate_text = request.run_id.value[:-1] + ("1" if request.run_id.value[-1] != "1" else "2")
        alternate = type(request.run_id)(alternate_text)
        try:
            self._run_pass(
                request,
                store=_WrongGenerationStore(self._store_factory(), alternate),
                preserve_errors=True,
            )
        except ConfluencePageSetError as exc:
            if exc.category.value != "raw_page_envelope_invalid":
                return False
        except Exception:
            return False
        else:
            return False
        try:
            self._run_pass(request, store=_CorruptEnvelopeStore(self._store_factory()), preserve_errors=True)
        except ConfluencePageSetError as exc:
            if exc.category.value != "raw_page_envelope_invalid":
                return False
        except Exception:
            return False
        else:
            return False
        current_source_version = request.items[0].expected_source_version
        mismatch_source_version = "__m8ac_mismatch__"
        suffix = 2
        while mismatch_source_version == current_source_version:
            mismatch_source_version = f"__m8ac_mismatch__{suffix}"
            suffix += 1
        mismatch_item = type(request.items[0])(
            page_id=request.items[0].page_id,
            crawled_at=request.items[0].crawled_at,
            expected_source_version=mismatch_source_version,
        )
        mismatch_request = MiniCorpusAcceptanceRequest(
            run_id=request.run_id,
            generation_id=request.generation_id,
            items=(mismatch_item,) + request.items[1:],
            profile_identity=request.profile_identity,
        )
        try:
            self._run_pass(mismatch_request, preserve_errors=True)
        except ConfluencePageSetError as exc:
            if exc.category.value != "source_version_mismatch":
                return False
        except Exception:
            return False
        else:
            return False
        try:
            self._run_pass(request, normalizer=_FailingNormalizer(self._normalizer), preserve_errors=True)
        except ConfluencePageSetError as exc:
            return exc.category.value == "normalization_failed"
        except Exception:
            return False
        return False

    def _expects_invalid_request(self, request: ConfluencePageSetRequest) -> bool:
        try:
            store = self._store_factory()
            ProcessConfluencePageSet(
                chunking_profile=self._profile,
                tokenizer=self._tokenizer,
                raw_page_store=store,
                raw_page_mapper=self._mapper,
                storage_normalizer=self._normalizer,
                schema_validator=self._validator,
            ).execute(request=request)
        except ConfluencePageSetError as exc:
            return exc.category.value == "invalid_request"
        except Exception:
            return False
        return False

    def _fingerprint(self) -> str:
        if self._source_fingerprint is None:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.SOURCE_INVALID)
        try:
            value = self._source_fingerprint()
        except Exception as exc:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.MUTATION_DETECTED) from exc
        if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.SOURCE_INVALID)
        return value

    def _write_fingerprint_value(self) -> str:
        try:
            value = self._write_fingerprint()
        except Exception as exc:
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.SOURCE_INVALID) from exc
        if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise MiniCorpusAcceptanceError(MiniCorpusAcceptanceFailureCategory.SOURCE_INVALID)
        return value

    @staticmethod
    def _summary_bytes(summaries: tuple[DocumentChunkSetSummary, ...]) -> bytes:
        return b"[" + b",".join(summary.to_canonical_json() for summary in summaries) + b"]"

    @staticmethod
    def _table_pages(result: ConfluencePageSetResult) -> int:
        document_ids = tuple(document["document_id"] for document in result.documents)
        page_has_table = {document_id: False for document_id in document_ids}
        for chunk in result.chunks:
            if chunk.get("content_kind") == "table":
                page_has_table[chunk["document_id"]] = True
        return sum(1 for value in page_has_table.values() if value)

    def _summary(
        self,
        *,
        request: MiniCorpusAcceptanceRequest,
        result: ConfluencePageSetResult,
        summaries: tuple[DocumentChunkSetSummary, ...],
        coverage: dict[str, int],
        page_set_digest: str,
        chunk_stability_digest: str,
        first_page_set_digest: str,
        second_page_set_digest: str,
        first_chunk_stability_digest: str,
        second_chunk_stability_digest: str,
        tokenizer_asset_digest: str,
        deterministic_repeat: bool,
        source_unchanged: bool,
        no_writes: bool,
        negative_pass: bool,
        duration_milliseconds: int,
    ) -> MiniCorpusAcceptanceSummary:
        page_counts = tuple(item.chunk_count for item in result.page_metrics)
        token_counts = tuple(
            chunk["token_count"]
            for chunk in result.chunks
            if type(chunk.get("token_count")) is int
        )
        content_kind_counts = result.metrics.content_kind_counts
        labels = (
            ("chunk_count_distribution", "OBSERVED" if page_counts else "NOT_APPLICABLE"),
            ("duration_milliseconds", "OBSERVED"),
            ("high_chunk_pages", "OBSERVED" if any(count > 1 for count in page_counts) else "NOT_APPLICABLE"),
            ("layout", "OBSERVED" if coverage["layout_page_count"] else "NOT_APPLICABLE"),
            ("reference", "OBSERVED" if coverage["reference_page_count"] else "NOT_APPLICABLE"),
            ("table", "OBSERVED" if coverage["table_page_count"] else "NOT_APPLICABLE"),
            ("token_count_distribution", "OBSERVED" if token_counts else "NOT_APPLICABLE"),
            ("zero_chunk_pages", "OBSERVED" if any(count == 0 for count in page_counts) else "NOT_APPLICABLE"),
        )
        return MiniCorpusAcceptanceSummary(
            status="complete",
            requested_pages=result.metrics.requested_pages,
            succeeded_pages=result.metrics.succeeded_pages,
            failed_pages=result.metrics.failed_pages,
            chunk_count=result.metrics.chunk_count,
            warning_count=result.metrics.warning_count,
            reference_intent_count=result.metrics.reference_intent_count,
            content_kind_counts=content_kind_counts,
            chunk_count_distribution=self._distribution(page_counts),
            token_count_distribution=self._distribution(token_counts),
            zero_chunk_pages=sum(1 for count in page_counts if count == 0),
            table_page_count=coverage["table_page_count"],
            layout_page_count=coverage["layout_page_count"],
            reference_page_count=coverage["reference_page_count"],
            page_set_digest=page_set_digest,
            chunk_stability_digest=chunk_stability_digest,
            first_page_set_digest=first_page_set_digest,
            second_page_set_digest=second_page_set_digest,
            first_chunk_stability_digest=first_chunk_stability_digest,
            second_chunk_stability_digest=second_chunk_stability_digest,
            tokenizer_asset_digest=tokenizer_asset_digest,
            profile_identity=request.profile_identity,
            chunker_version=self._profile.chunker_version,
            deterministic_repeat=deterministic_repeat,
            source_unchanged=source_unchanged,
            negative_pass=negative_pass,
            no_writes=no_writes,
            report_leak_free=True,
            distribution_labels=labels,
            ordinal_statuses=tuple((index, "succeeded", None) for index in range(1, result.metrics.requested_pages + 1)),
            duration_milliseconds=duration_milliseconds,
        )

    def _tokenizer_asset_digest(self) -> str:
        payload = [
            [asset.filename, asset.byte_size, asset.sha256]
            for asset in self._profile.tokenizer_assets
        ]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _report_is_leak_free(serialized: bytes) -> bool:
        lowered = serialized.lower()
        forbidden = (
            b"page_id",
            b"body_bytes",
            b"storage_xhtml",
            b"title",
            b"filename",
            b"credential",
            b"http://",
            b"https://",
            b"data_root",
            b"tokenizer_assets_dir",
            b"\\",
        )
        return not any(marker in lowered for marker in forbidden)

    @staticmethod
    def _distribution(values: tuple[int, ...]) -> tuple[int, int, int, int]:
        if not values:
            return (0, 0, 0, 0)
        ordered = tuple(sorted(values))
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return (
            ordered[0],
            ordered[(len(ordered) - 1) // 2],
            ordered[p95_index],
            ordered[-1],
        )


__all__ = ["AcceptConfluenceMiniCorpus"]
