from __future__ import annotations

import pytest

from knowledgenexus.foundation.infrastructure.adapters.m10_source_adapters import (
    ConfluenceM10Adapter,
    ConfluenceM10MaterializedSource,
    ConfluenceMaterializedInput,
    GitM10Adapter,
    GitM10MaterializedSource,
    GitMaterializedInput,
    M10SourceAdapterError,
)
from knowledgenexus.foundation.application.use_cases.compose_m10_snapshot import ComposeM10Snapshot
from tests.foundation.domain.models.test_m10_composition import _handoffs, _request


class Provider:
    def __init__(self, value: object):
        self.value = value

    def collect(self, request: object) -> object:
        return self.value


def test_concrete_adapters_assemble_handoffs_and_sync_rows(tmp_path) -> None:
    confluence, git = _handoffs()
    request = _request(tmp_path)
    confluence_input = ConfluenceMaterializedInput(
        confluence.source_version,
        confluence.raw_artifact_identity,
        confluence.documents,
        confluence.chunks,
        confluence.relations,
        confluence.acl,
        (),
    )
    git_input = GitMaterializedInput(git.documents, git.chunks, git.acl, git.symbols)
    confluence_handoff = ConfluenceM10Adapter(source=Provider(confluence_input)).collect(request)
    git_handoff = GitM10Adapter(source=Provider(git_input)).collect(request)
    assert confluence_handoff.sync_state[0]["entity_type"] == "page"
    assert {row["entity_type"] for row in git_handoff.sync_state} == {"file", "repo"}


def test_concrete_adapters_feed_composition_boundary(tmp_path) -> None:
    confluence, git = _handoffs()
    request = _request(tmp_path)
    confluence_input = ConfluenceMaterializedInput(
        confluence.source_version,
        confluence.raw_artifact_identity,
        confluence.documents,
        confluence.chunks,
        confluence.relations,
        confluence.acl,
        (),
    )
    git_input = GitMaterializedInput(git.documents, git.chunks, git.acl, git.symbols)
    result = ComposeM10Snapshot(
        confluence_adapter=ConfluenceM10Adapter(source=Provider(confluence_input)),
        git_adapter=GitM10Adapter(source=Provider(git_input)),
    ).execute(request)
    assert result.projection is not None
    assert result.projection.metrics.sync_state == 3


@pytest.mark.parametrize("bad", [None, object(), "bad"])
def test_adapter_rejects_wrong_provider_output_without_leaking_details(tmp_path, bad) -> None:
    adapter = ConfluenceM10Adapter(source=Provider(bad))
    with pytest.raises(M10SourceAdapterError) as exc_info:
        adapter.collect(_request(tmp_path))
    assert str(exc_info.value) == "Confluence collection failed"


def test_adapter_rejects_wrong_runtime_request_before_provider_call(tmp_path) -> None:
    class Exploding:
        def collect(self, request: object) -> object:
            raise RuntimeError("should not be called")

    with pytest.raises(M10SourceAdapterError) as exc_info:
        ConfluenceM10Adapter(source=Exploding()).collect(object())  # type: ignore[arg-type]
    assert str(exc_info.value) == "invalid request"


class _Output:
    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


def test_materialized_sources_compose_injected_foundation_stages(tmp_path) -> None:
    confluence, git = _handoffs()
    request = _request(tmp_path)

    page = _Output(
        source_version=confluence.source_version,
        raw_artifact_identity=confluence.raw_artifact_identity,
        documents=confluence.documents,
        chunks=confluence.chunks,
    )

    class PageStage:
        def execute(self, request):
            assert request is not None
            return page

    class RelationStage:
        def execute(self, request, **state):
            assert state["documents"] == confluence.documents
            return confluence.relations

    class GitStage:
        def execute(self, request):
            return _Output(documents=git.documents, chunks=git.chunks)

    class SymbolStage:
        def execute(self, request, **state):
            return _Output(symbol_records=git.symbols)

    confluence_input = ConfluenceM10MaterializedSource(
        page_stage=PageStage(), relation_stage=RelationStage()
    ).collect(request)
    git_input = GitM10MaterializedSource(
        document_stage=GitStage(), symbol_stage=SymbolStage()
    ).collect(request)
    assert confluence_input.relations == confluence.relations
    assert git_input.symbols == git.symbols
    assert ConfluenceM10Adapter(source=Provider(confluence_input)).collect(request).documents == confluence.documents
    assert GitM10Adapter(source=Provider(git_input)).collect(request).documents == git.documents


@pytest.mark.parametrize("bad", [None, object(), {"documents": ()}])
def test_materialized_sources_fail_closed_on_bad_stage_output(tmp_path, bad) -> None:
    request = _request(tmp_path)

    class BadStage:
        def execute(self, request):
            return bad

    with pytest.raises((TypeError, ValueError)):
        ConfluenceM10MaterializedSource(page_stage=BadStage()).collect(request)
    with pytest.raises((TypeError, ValueError)):
        GitM10MaterializedSource(document_stage=BadStage()).collect(request)


def test_materialized_sources_reject_wrong_request_before_stage_call(tmp_path) -> None:
    class Exploding:
        def execute(self, request):
            raise AssertionError("must not be called")

    with pytest.raises(TypeError, match="invalid request"):
        ConfluenceM10MaterializedSource(page_stage=Exploding()).collect(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="invalid request"):
        GitM10MaterializedSource(document_stage=Exploding()).collect(object())  # type: ignore[arg-type]


def test_adapter_sanitizes_unexpected_provider_exception(tmp_path) -> None:
    class Exploding:
        def collect(self, request):
            raise RuntimeError("connector secret")

    with pytest.raises(M10SourceAdapterError) as exc_info:
        ConfluenceM10Adapter(source=Exploding()).collect(_request(tmp_path))
    assert str(exc_info.value) == "Confluence collection failed"
