"""Tests for IngestConfluencePage use case."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from knowledgenexus.foundation.domain.models import (
    CharacterSpan,
    ChunkingProfile,
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
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.indexing.application.use_cases.ingest_confluence_page import (
    IngestConfluencePage,
)
from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)

RUN_ID = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")


class _WordTokenizer:
    def tokenize(self, *, text: str) -> TokenizationResult:
        return TokenizationResult(
            spans=tuple(
                CharacterSpan(match.start(), match.end())
                for match in re.finditer(r"\S+", text)
            )
        )


class _MockEmbedder:
    model_name = "test-embedder"
    dimension = 8
    supports_sparse = False

    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        return [
            EmbeddingVector(
                values=[0.1] * self.dimension,
                model_name=self.model_name,
                dimension=self.dimension,
                sparse=None,
            )
            for _ in texts
        ]

    async def embed_query(self, query: str) -> EmbeddingVector:
        return EmbeddingVector(
            values=[0.1] * self.dimension,
            model_name=self.model_name,
            dimension=self.dimension,
            sparse=None,
        )


class _MockChunkStorageService:
    def __init__(self) -> None:
        self.saved_chunks = []

    async def save(self, chunks) -> None:
        self.saved_chunks.extend(chunks)


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


def _raw_body(*, page_id: str, title: str) -> bytes:
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


@pytest.fixture
def raw_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


async def test_ingest_confluence_page_end_to_end(raw_root):
    page_id = "1000"
    store = ConfluenceRawPageGenerationStore(raw_root=raw_root)
    store.publish_page(
        envelope=ConfluenceRawPageEnvelope.capture(
            run_id=RUN_ID,
            page_id=page_id,
            source_version="7",
            http_status=200,
            body_bytes=_raw_body(page_id=page_id, title="Test Page"),
        )
    )

    embedder = _MockEmbedder()
    storage_service = _MockChunkStorageService()
    use_case = IngestConfluencePage(
        chunking_profile=_profile(),
        tokenizer=_WordTokenizer(),
        raw_page_store=store,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
        embedder=embedder,
        chunk_storage_service=storage_service,
    )

    result = await use_case.execute(run_id=RUN_ID, page_id=page_id)

    assert result.status == "success"
    assert result.chunks_ingested >= 1
    assert result.chunks_failed == 0
    assert len(storage_service.saved_chunks) == result.chunks_ingested
    assert all(
        "Test Page" in chunk.content or "Body for Test Page" in chunk.content
        for chunk in storage_service.saved_chunks
    )


async def test_ingest_confluence_page_missing_page_raises(raw_root):
    store = ConfluenceRawPageGenerationStore(raw_root=raw_root)
    use_case = IngestConfluencePage(
        chunking_profile=_profile(),
        tokenizer=_WordTokenizer(),
        raw_page_store=store,
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=FoundationSchemaValidator(),
        embedder=_MockEmbedder(),
        chunk_storage_service=_MockChunkStorageService(),
    )

    with pytest.raises(Exception):
        await use_case.execute(run_id=RUN_ID, page_id="404404")
