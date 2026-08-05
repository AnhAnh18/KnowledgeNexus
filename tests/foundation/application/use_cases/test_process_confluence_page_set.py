from __future__ import annotations

import json
import re
from dataclasses import replace

import pytest

from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import (
    ProcessConfluencePageSet,
)
from knowledgenexus.foundation.domain.models import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    CharacterSpan,
    ChunkingProfile,
    ConfluencePageSetError,
    ConfluencePageSetFailureCategory,
    ConfluencePageSetRequest,
    ConfluencePageWorkItem,
    CrawlRunId,
    TokenizationResult,
    TokenizerAsset,
)
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


RUN_ID = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
CRAWLED_AT = "2026-07-22T00:00:00Z"


def _profile() -> ChunkingProfile:
    return ChunkingProfile(
        chunker_version="1.2.0",
        profile_status="provisional_until_benchmark",
        active_profile="medium",
        model_name="BAAI/bge-m3",
        tokenizer_name="BAAI/bge-m3",
        tokenizer_family="SentencePiece / XLM-R",
        vector_dimension=1024,
        maximum_model_tokens=8192,
        target_tokens=450,
        minimum_tokens=96,
        hard_maximum_tokens=1000,
        overlap_tokens=64,
        code_window_target_tokens=450,
        code_window_max_lines=40,
        code_window_overlap_lines=4,
        tokenizer_repository="https://huggingface.co/BAAI/bge-m3",
        tokenizer_revision="5617a9f61b028005a4858fdac845db406aefb181",
        observed_license="MIT",
        provenance_url="https://huggingface.co/BAAI/bge-m3/tree/"
        "5617a9f61b028005a4858fdac845db406aefb181",
        tokenizer_assets=(
            TokenizerAsset(
                filename="tokenizer.json",
                byte_size=17098108,
                sha256="21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
            ),
        ),
        transformers_version="4.57.6",
        tokenizers_version="0.22.2",
        sentencepiece_version="0.2.2",
    )


class _WordTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(
            spans=tuple(
                CharacterSpan(match.start(), match.end())
                for match in re.finditer(r"\S+", text)
            )
        )


def _raw(*, page_id: str, title: str, source_version: str = "7") -> bytes:
    return json.dumps(
        {
            "id": page_id,
            "type": "page",
            "title": title,
            "space": {"key": "SPACE"},
            "version": {"number": int(source_version), "when": "2026-07-21T00:00:00Z"},
            "body": {
                "storage": {
                    "value": f"<h2>{title}</h2><p>Body for {title}</p>",
                    "representation": "storage",
                }
            },
        },
        separators=(",", ":"),
    ).encode()


class _Store:
    def __init__(self, envelopes: dict[str, ConfluenceRawPageEnvelope]) -> None:
        self.envelopes = envelopes
        self.calls: list[tuple[CrawlRunId, str]] = []

    def read_page(self, *, run_id: CrawlRunId, page_id: str) -> ConfluenceRawPageEnvelope:
        self.calls.append((run_id, page_id))
        return self.envelopes[page_id]


def _request(*page_ids: str, expected: str | None = "7") -> ConfluencePageSetRequest:
    return ConfluencePageSetRequest(
        run_id=RUN_ID,
        generation_id=RUN_ID,
        items=tuple(
            ConfluencePageWorkItem(
                page_id=page_id,
                crawled_at=CRAWLED_AT,
                expected_source_version=expected,
            )
            for page_id in page_ids
        ),
        profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    )


def _use_case(store: _Store, *, storage_normalizer: object | None = None) -> ProcessConfluencePageSet:
    return ProcessConfluencePageSet(
        chunking_profile=_profile(),
        tokenizer=_WordTokenizer(),
        raw_page_store=store,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=storage_normalizer or ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
    )


def _store_for(*page_ids: str) -> _Store:
    return _Store(
        {
            page_id: ConfluenceRawPageEnvelope.capture(
                run_id=RUN_ID,
                page_id=page_id,
                source_version="7",
                http_status=200,
                body_bytes=_raw(page_id=page_id, title=f"Page {page_id}"),
            )
            for page_id in page_ids
        }
    )


def test_page_set_is_ordered_schema_valid_and_repeatable() -> None:
    store = _store_for("1000", "1001")
    use_case = _use_case(store)
    first = use_case.execute(request=_request("1001", "1000"))
    second = use_case.execute(request=_request("1001", "1000"))

    assert [document["page_id"] for document in first.documents] == ["1001", "1000"]
    assert first.metrics.requested_pages == 2
    assert first.metrics.succeeded_pages == 2
    assert first.metrics.failed_pages == 0
    assert first.to_canonical_json() == second.to_canonical_json()
    validator = FoundationSchemaValidator()
    for document in first.documents:
        validator.validate_record("CanonicalDocument", document)
    for chunk in first.chunks:
        validator.validate_record("ChunkRecord", chunk)


def test_page_set_rejects_later_failure_without_partial_result_or_leak() -> None:
    store = _store_for("1000", "1001")
    del store.envelopes["1001"]
    with pytest.raises(ConfluencePageSetError) as caught:
        _use_case(store).execute(request=_request("1000", "1001"))
    assert caught.value.category == ConfluencePageSetFailureCategory.RAW_PAGE_READ_FAILED
    assert caught.value.page_ordinal == 2
    assert caught.value.succeeded_pages == 1
    assert "1001" not in str(caught.value)
    assert "Page 1001" not in repr(caught.value)


def test_wrong_status_fails_closed() -> None:
    envelope = ConfluenceRawPageEnvelope.capture(
        run_id=RUN_ID,
        page_id="1000",
        source_version="7",
        http_status=403,
        body_bytes=_raw(page_id="1000", title="Private"),
    )
    store = _Store({"1000": envelope})
    with pytest.raises(ConfluencePageSetError) as caught:
        _use_case(store).execute(request=_request("1000"))
    assert caught.value.category == ConfluencePageSetFailureCategory.RAW_PAGE_STATUS_FAILED


def test_expected_source_version_mismatch_is_categorized() -> None:
    envelope = ConfluenceRawPageEnvelope.capture(
        run_id=RUN_ID,
        page_id="1000",
        source_version="8",
        http_status=200,
        body_bytes=_raw(page_id="1000", title="Page 1000", source_version="8"),
    )
    store = _Store({"1000": envelope})
    with pytest.raises(ConfluencePageSetError) as caught:
        _use_case(store).execute(request=_request("1000", expected="7"))
    assert caught.value.category == ConfluencePageSetFailureCategory.SOURCE_VERSION_MISMATCH


def test_omitted_expected_version_still_checks_envelope_and_document() -> None:
    store = _store_for("1000")
    result = _use_case(store).execute(request=_request("1000", expected=None))
    assert result.documents[0]["source_version"] == "7"


def test_profile_numeric_drift_is_rejected_before_store_read() -> None:
    store = _store_for("1000")
    with pytest.raises(ValueError):
        ProcessConfluencePageSet(
            chunking_profile=replace(_profile(), target_tokens=451),
            tokenizer=_WordTokenizer(),
            raw_page_store=store,
            raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
            storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        )
    assert store.calls == []


def test_profile_asset_drift_is_rejected_before_store_read() -> None:
    store = _store_for("1000")
    with pytest.raises(ValueError):
        ProcessConfluencePageSet(
            chunking_profile=replace(
                _profile(),
                tokenizer_assets=(
                    TokenizerAsset(
                        filename="tokenizer.json",
                        byte_size=1,
                        sha256="0" * 64,
                    ),
                ),
            ),
            tokenizer=_WordTokenizer(),
            raw_page_store=store,
            raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
            storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        )
    assert store.calls == []


def test_malformed_normalizer_return_is_categorized() -> None:
    class BadNormalizer:
        def normalize(self, *, storage_xhtml: str) -> object:
            return None

    store = _store_for("1000")
    with pytest.raises(ConfluencePageSetError) as caught:
        _use_case(store, storage_normalizer=BadNormalizer()).execute(
            request=_request("1000")
        )
    assert caught.value.category == ConfluencePageSetFailureCategory.NORMALIZATION_FAILED


def test_malformed_nested_chunk_record_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    import knowledgenexus.foundation.application.use_cases.process_confluence_page_set as module
    from knowledgenexus.foundation.domain.models.confluence_chunking import ChunkingResult

    class FakeChunker:
        def __init__(self, **kwargs: object) -> None:
            pass

        def execute(self, **kwargs: object) -> ChunkingResult:
            return ChunkingResult(
                records=({"content_kind": "prose", "nested": object()},),
                metrics={},
            )

    monkeypatch.setattr(module, "BuildConfluenceChunks", FakeChunker)
    with pytest.raises(ConfluencePageSetError) as caught:
        _use_case(_store_for("1000")).execute(request=_request("1000"))
    assert caught.value.category == ConfluencePageSetFailureCategory.CHUNKING_FAILED


def test_result_ownership_isolated() -> None:
    use_case = _use_case(_store_for("1000"))
    result = use_case.execute(request=_request("1000"))
    result.documents[0]["metadata"]["mutated"] = True
    repeat = use_case.execute(request=_request("1000"))
    assert "mutated" not in repeat.documents[0]["metadata"]


def test_unordered_or_invalid_request_fails_before_store_read() -> None:
    store = _store_for("1000")
    with pytest.raises(TypeError):
        ConfluencePageSetRequest(
            run_id=RUN_ID,
            generation_id=RUN_ID,
            items=[ConfluencePageWorkItem(page_id="1000", crawled_at=CRAWLED_AT)],  # type: ignore[arg-type]
            profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
        )
    assert store.calls == []


@pytest.mark.parametrize("bad_request", [None, object()])
def test_malformed_request_object_fails_closed_before_store_read(bad_request: object) -> None:
    store = _store_for("1000")
    with pytest.raises(ConfluencePageSetError) as caught:
        _use_case(store).execute(request=bad_request)  # type: ignore[arg-type]
    assert caught.value.category == ConfluencePageSetFailureCategory.INVALID_REQUEST
    assert store.calls == []
