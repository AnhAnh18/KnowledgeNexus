from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from knowledgenexus.foundation.domain.models import GitCasePolicy, GitScanBudgets
from knowledgenexus.foundation.infrastructure.adapters.m10_composition_root import (
    ConfluenceM10CompositionRoot,
    GitM10CompositionRoot,
)
from knowledgenexus.foundation.infrastructure.adapters.m10_composition_root import _ConfluencePageSetStage
from tests.foundation.application.use_cases.test_build_git_code_documents import (
    FakeReader,
    FakeTokenizer,
    _snapshot,
)
from tests.foundation.domain.models.test_m10_composition import _request


class _SchemaValidator:
    def validate_record(self, schema_name: str, record: dict[str, object]) -> None:
        return None


def test_confluence_page_root_translates_m10_scope_to_approved_page_set(tmp_path: Path) -> None:
    from knowledgenexus.foundation.domain.models.confluence_page_set import (
        ConfluencePageSetMetrics,
        ConfluencePageSetPageMetrics,
        ConfluencePageSetResult,
    )

    class Processor:
        def __init__(self) -> None:
            self.request = None

        def execute(self, *, request):
            self.request = request
            return ConfluencePageSetResult(
                documents=({"source_version": "7"},),
                chunks=(),
                page_metrics=(ConfluencePageSetPageMetrics(1, 0, 0, 0, ()),),
                metrics=ConfluencePageSetMetrics(1, 1, 0, 1, 0, 0, 0, ()),
            )

    processor = Processor()
    request = _request(tmp_path)
    output = _ConfluencePageSetStage(processor).execute(request=request)
    assert output.source_version == "7"
    assert output.raw_artifact_identity == request.raw_generation_id
    assert processor.request.items[0].page_id == request.ordered_page_ids[0]


def test_confluence_root_rejects_unconfigured_approved_seams() -> None:
    with pytest.raises(TypeError, match="chunking_profile|page processor|tokenizer|raw_page_store"):
        ConfluenceM10CompositionRoot.build(
            raw_page_store=object(),
            tokenizer=object(),
            chunking_profile=object(),
            raw_page_mapper=object(),
            storage_normalizer=object(),
            schema_validator=_SchemaValidator(),
        )


def test_git_root_binds_pinned_reader_and_materializes_acl_sync(tmp_path: Path) -> None:
    repository_root = tmp_path / "spen-sdk"
    repository_root.mkdir()
    request = replace(
        _request(tmp_path),
        git_repository="spen-sdk",
        git_branch="develop",
    )
    adapter = GitM10CompositionRoot.build(
        repository_reader=FakeReader(_snapshot()),
        tokenizer=FakeTokenizer(),
        repository_root=repository_root,
        budgets=GitScanBudgets(
            max_tree_entries=100,
            max_file_bytes=4096,
            max_total_raw_bytes=8192,
            max_files=20,
            max_normalized_bytes=4096,
            max_in_memory_bytes=16384,
        ),
        case_policy=GitCasePolicy.REJECT_CASEFOLD_COLLISIONS,
        schema_validator=_SchemaValidator(),
    )
    handoff = adapter.collect(request)
    assert handoff.documents
    assert len(handoff.acl) == len(handoff.documents)
    assert {row["entity_type"] for row in handoff.sync_state} == {"file", "repo"}


def test_git_root_rejects_wrong_runtime_dependencies(tmp_path: Path) -> None:
    root = tmp_path / "spen-sdk"
    root.mkdir()
    with pytest.raises(TypeError):
        GitM10CompositionRoot.build(
            repository_reader=object(),
            tokenizer=FakeTokenizer(),
            repository_root=root,
            budgets=GitScanBudgets(100, 4096, 8192, 20, 4096, 16384),
            case_policy=GitCasePolicy.REJECT_CASEFOLD_COLLISIONS,
        )
