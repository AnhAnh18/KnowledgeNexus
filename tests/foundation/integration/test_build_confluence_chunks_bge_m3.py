from __future__ import annotations

import socket
from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases import BuildConfluenceChunks
from knowledgenexus.foundation.domain.records import (
    CanonicalDocumentRecordBuilder,
    ChunkRecordBuilder,
)
from knowledgenexus.foundation.domain.rules import ChunkIdGenerator
from knowledgenexus.foundation.domain.rules import TextNormalizationRules
from knowledgenexus.foundation.domain.rules.wiki_structure_parser import (
    WikiStructureParser,
)
from knowledgenexus.foundation.infrastructure.config import load_chunking_profile
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = REPOSITORY_ROOT / "contracts" / "foundation" / "embedding_profile.yaml"


def test_real_bge_m3_forced_split_is_exact_schema_valid_and_deterministic(
    tokenizer_assets_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> object:
        raise AssertionError("M6D-D real-tokenizer path attempted network access")

    monkeypatch.setattr(socket, "create_connection", forbid_network)
    profile = load_chunking_profile(PROFILE_PATH)
    tokenizer = BgeM3LocalTokenizer(
        profile=profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    validator = FoundationSchemaValidator()
    use_case = BuildConfluenceChunks(
        profile=profile,
        tokenizer=tokenizer,
        chunk_id_generator=ChunkIdGenerator,
        chunk_record_builder=ChunkRecordBuilder,
        schema_validator=validator,
    )
    long_prose = "\n\n".join(
        f"Đoạn kiến thức nền tảng đa ngôn ngữ số {index}. " + "token " * 25
        for index in range(45)
    )
    body = TextNormalizationRules.normalize_text(
        f"## Architecture\n\n{long_prose}\n\n"
        "## Table\n\n| Key | Value |\n| --- | --- |\n| A | B |\n\n"
        "## Code\n\n```python\ndef build():\n    return 1\n```"
    )
    canonical = CanonicalDocumentRecordBuilder.build(
        document_id="confluence:page:1000",
        source_system="confluence",
        source_type="wiki_page",
        normalized_body_text=body,
        acl_id="acl:confluence:page:1000",
        crawled_at="2026-07-22T00:00:00Z",
        title="Fixture Foundation",
        space_key="SPACE",
        page_id="1000",
        source_version="9",
        jira_keys=[],
        relation_ids=[],
        updated_at="2026-07-20T01:02:03Z",
        metadata={},
    )
    structure = WikiStructureParser.parse(
        page_title="Fixture Foundation",
        normalized_body_text=body,
    )

    first = use_case.execute(canonical_document=canonical, structure=structure)
    second = use_case.execute(canonical_document=canonical, structure=structure)

    assert first.records == second.records
    assert first.metrics == second.metrics
    assert len(first.records) > 3
    assert first.metrics["oversize_splits"] >= 1
    assert first.metrics["chunks_over_hard_max"] == 0
    assert {record["content_kind"] for record in first.records} == {
        "prose",
        "table",
        "code_block",
    }
    for record in first.records:
        validator.validate_record("ChunkRecord", record)
        text = record["text"]
        assert isinstance(text, str)
        assert record["token_count"] == tokenizer.tokenize(text=text).token_count
        assert record["token_count"] <= profile.hard_maximum_tokens
        assert record["acl_tags"] == ["restricted:unresolved"]
