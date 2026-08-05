from __future__ import annotations

import json
import re

import pytest

from knowledgenexus.foundation.application.use_cases.accept_confluence_mini_corpus import (
    AcceptConfluenceMiniCorpus,
)
from knowledgenexus.foundation.domain.models import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    CharacterSpan,
    ChunkingProfile,
    ConfluencePageWorkItem,
    CrawlRunId,
    TokenizationResult,
    TokenizerAsset,
)
from knowledgenexus.foundation.domain.models.confluence_mini_corpus_acceptance import (
    MiniCorpusAcceptanceError,
    MiniCorpusAcceptanceFailureCategory,
    MiniCorpusAcceptanceRequest,
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


class _Tokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(
            spans=tuple(
                CharacterSpan(match.start(), match.end())
                for match in re.finditer(r"\S+", text)
            )
        )


def _raw(page_id: str) -> bytes:
    title = f"Page {page_id}"
    return json.dumps(
        {
            "id": page_id,
            "type": "page",
            "title": title,
            "space": {"key": "SPACE"},
            "version": {"number": 7, "when": "2026-07-21T00:00:00Z"},
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
    def __init__(self) -> None:
        self.envelopes = {
            str(1000 + index): ConfluenceRawPageEnvelope.capture(
                run_id=RUN_ID,
                page_id=str(1000 + index),
                source_version="7",
                http_status=200,
                body_bytes=_raw(str(1000 + index)),
            )
            for index in range(10)
        }

    def read_page(self, *, run_id: CrawlRunId, page_id: str) -> ConfluenceRawPageEnvelope:
        return self.envelopes[page_id]


def _request() -> MiniCorpusAcceptanceRequest:
    return MiniCorpusAcceptanceRequest(
        run_id=RUN_ID,
        generation_id=RUN_ID,
        items=tuple(
            ConfluencePageWorkItem(
                page_id=str(1000 + index),
                crawled_at="2026-07-22T00:00:00Z",
                expected_source_version="7",
            )
            for index in range(10)
        ),
    )


def test_twenty_page_shape_harness_runs_two_deterministic_passes() -> None:
    acceptance = AcceptConfluenceMiniCorpus(
        chunking_profile=_profile(),
        tokenizer=_Tokenizer(),
        raw_page_store_factory=_Store,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
        source_fingerprint=lambda: "a" * 64,
        write_fingerprint=lambda: "b" * 64,
    )
    summary = acceptance.execute(request=_request())
    assert summary.status == "complete"
    assert summary.requested_pages == 10
    assert summary.succeeded_pages == 10
    assert summary.deterministic_repeat is True
    assert summary.negative_pass is True
    assert summary.no_writes is True
    assert summary.report_leak_free is True


def test_source_mutation_fails_closed_with_sanitized_category() -> None:
    fingerprints = iter(("a" * 64, "b" * 64))
    acceptance = AcceptConfluenceMiniCorpus(
        chunking_profile=_profile(),
        tokenizer=_Tokenizer(),
        raw_page_store_factory=_Store,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
        source_fingerprint=lambda: next(fingerprints),
        write_fingerprint=lambda: "b" * 64,
    )
    with pytest.raises(MiniCorpusAcceptanceError) as error:
        acceptance.execute(request=_request())
    assert error.value.category is MiniCorpusAcceptanceFailureCategory.MUTATION_DETECTED


def test_write_observer_mutation_fails_even_when_selected_pages_are_stable() -> None:
    write_fingerprints = iter(("a" * 64, "b" * 64))
    acceptance = AcceptConfluenceMiniCorpus(
        chunking_profile=_profile(),
        tokenizer=_Tokenizer(),
        raw_page_store_factory=_Store,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
        source_fingerprint=lambda: "c" * 64,
        write_fingerprint=lambda: next(write_fingerprints),
    )
    with pytest.raises(MiniCorpusAcceptanceError) as error:
        acceptance.execute(request=_request())
    assert error.value.category is MiniCorpusAcceptanceFailureCategory.MUTATION_DETECTED
