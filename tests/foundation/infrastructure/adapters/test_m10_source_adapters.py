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
from knowledgenexus.foundation.application.use_cases.materialize_confluence_media_relations import MaterializeConfluenceMediaRelations
from knowledgenexus.foundation.domain.models import MediaMaterializationResult
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


def test_confluence_materialized_source_runs_media_before_relation_stage(tmp_path) -> None:
    confluence, _ = _handoffs()
    request = _request(tmp_path)
    page = _Output(
        source_version=confluence.source_version,
        raw_artifact_identity=confluence.raw_artifact_identity,
        documents=confluence.documents,
        chunks=confluence.chunks,
    )
    events: list[str] = []

    class PageStage:
        def execute(self, request):
            return page

    class MediaStage:
        def execute(self, request, **state):
            assert "media_assets" in state
            events.append("media")
            return _Output(media_assets=())

    class RelationStage:
        def execute(self, request, **state):
            assert state["media_assets"] == ()
            events.append("relation")
            return confluence.relations

    result = ConfluenceM10MaterializedSource(
        page_stage=PageStage(), media_stage=MediaStage(), relation_stage=RelationStage()
    ).collect(request)
    assert events == ["media", "relation"]
    assert result.relations == confluence.relations


def test_confluence_materialized_source_runs_acl_before_generic_relations(tmp_path) -> None:
    confluence, _ = _handoffs()
    request = _request(tmp_path)
    page = _Output(
        source_version=confluence.source_version,
        raw_artifact_identity=confluence.raw_artifact_identity,
        documents=confluence.documents,
        chunks=confluence.chunks,
    )
    events: list[str] = []

    class PageStage:
        def execute(self, request):
            return page

    class AclStage:
        def execute(self, request, **state):
            assert state["documents"] == confluence.documents
            events.append("acl")
            return _Output(
                documents=tuple({**row, "acl_tags": ["space:SVMC"]} for row in confluence.documents),
                chunks=tuple({**row, "acl_tags": ["space:SVMC"]} for row in confluence.chunks),
                acl=confluence.acl,
            )

    class RelationStage:
        def execute(self, request, **state):
            assert state["documents"][0]["acl_tags"] == ["space:SVMC"]
            assert state["chunks"][0]["acl_tags"] == ["space:SVMC"]
            events.append("relation")
            return confluence.relations

    result = ConfluenceM10MaterializedSource(
        page_stage=PageStage(), acl_stage=AclStage(), relation_stage=RelationStage()
    ).collect(request)
    assert events == ["acl", "relation"]
    assert result.relations == confluence.relations


def test_confluence_materialized_source_wires_keyword_only_media_relation_stage_and_keeps_enrichment(tmp_path) -> None:
    confluence, _ = _handoffs()
    request = _request(tmp_path)
    media = MediaMaterializationResult(assets=(), relation_intents=())
    page = _Output(
        source_version=confluence.source_version,
        raw_artifact_identity=confluence.raw_artifact_identity,
        documents=confluence.documents,
        chunks=confluence.chunks,
        media_result=media,
    )
    enriched_documents = tuple({**record, "metadata": {"enriched": True}} for record in confluence.documents)
    enriched_chunks = tuple({**record, "text": "enriched"} for record in confluence.chunks)

    class PageStage:
        def execute(self, request):
            return page

    class EnrichingRelationStage:
        # Match MaterializeConfluenceMediaRelations' keyword-only seam.
        def execute(self, *, documents, chunks, media, page_references=(), page_targets=()):
            assert documents == confluence.documents
            assert chunks == confluence.chunks
            assert media is media_result
            assert page_references == ()
            assert page_targets == ()
            return _Output(documents=enriched_documents, chunks=enriched_chunks, relations=())

    media_result = media
    result = ConfluenceM10MaterializedSource(
        page_stage=PageStage(), relation_stage=EnrichingRelationStage()
    ).collect(request)
    assert result.documents == enriched_documents
    assert result.chunks == enriched_chunks


def test_confluence_materialized_source_accepts_actual_media_relation_materializer(tmp_path) -> None:
    confluence, _ = _handoffs()
    request = _request(tmp_path)
    page = _Output(
        source_version=confluence.source_version,
        raw_artifact_identity=confluence.raw_artifact_identity,
        documents=confluence.documents,
        chunks=confluence.chunks,
        media_result=MediaMaterializationResult(assets=(), relation_intents=()),
    )

    class PageStage:
        def execute(self, request):
            return page

    result = ConfluenceM10MaterializedSource(
        page_stage=PageStage(), relation_stage=MaterializeConfluenceMediaRelations()
    ).collect(request)
    assert result.documents == confluence.documents
    assert result.chunks == confluence.chunks


def test_confluence_materialized_source_accepts_combined_materializer_at_media_seam(tmp_path) -> None:
    confluence, _ = _handoffs()
    request = _request(tmp_path)
    page = _Output(
        source_version=confluence.source_version,
        raw_artifact_identity=confluence.raw_artifact_identity,
        documents=confluence.documents,
        chunks=confluence.chunks,
        media_result=MediaMaterializationResult(assets=(), relation_intents=()),
    )

    class PageStage:
        def execute(self, request):
            return page

    result = ConfluenceM10MaterializedSource(
        page_stage=PageStage(), media_stage=MaterializeConfluenceMediaRelations()
    ).collect(request)
    assert result.documents == confluence.documents
    assert result.chunks == confluence.chunks


@pytest.mark.parametrize(
    "missing",
    ["source_version", "raw_artifact_identity"],
)
def test_confluence_materialized_source_requires_stage_provenance(tmp_path, missing) -> None:
    confluence, _ = _handoffs()
    request = _request(tmp_path)
    values = {
        "source_version": confluence.source_version,
        "raw_artifact_identity": confluence.raw_artifact_identity,
        "documents": confluence.documents,
        "chunks": confluence.chunks,
    }
    values.pop(missing)

    class PageStage:
        def execute(self, request):
            return _Output(**values)

    with pytest.raises(ValueError, match="page stage provenance is invalid"):
        ConfluenceM10MaterializedSource(page_stage=PageStage()).collect(request)


def test_adapter_sanitizes_unexpected_provider_exception(tmp_path) -> None:
    class Exploding:
        def collect(self, request):
            raise RuntimeError("connector secret")

    with pytest.raises(M10SourceAdapterError) as exc_info:
        ConfluenceM10Adapter(source=Exploding()).collect(_request(tmp_path))
    assert str(exc_info.value) == "Confluence collection failed"
