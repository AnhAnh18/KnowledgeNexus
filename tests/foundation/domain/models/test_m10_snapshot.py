import pytest
from pathlib import Path

from knowledgenexus.foundation.domain.models.m10_snapshot import (
    M10ConfluenceExclusion, M10ConfluenceScope, M10MediaPolicy,
    M10SnapshotError, M10SnapshotMetrics, M10SnapshotProjection,
    M10SnapshotResult, M10QualityReportInput, M10ProfileIdentity,
)
from knowledgenexus.foundation.domain.models.chunk_stability import ACTIVE_CHUNKER_VERSION

def scope():
    return M10ConfluenceScope("src", ("A",), ("1",), ("1", "2"))

def metrics():
    return M10SnapshotMetrics(2, 2, 0, 2, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0)

def test_scope_and_policy_are_canonical():
    assert scope().page_ids == ("1", "2")
    assert M10MediaPolicy(False, False, (), 0).max_assets == 0
    with pytest.raises(M10SnapshotError): M10ConfluenceScope("src", ("B", "A"), ("1",), ("1",))
    with pytest.raises(M10SnapshotError): M10MediaPolicy(False, True, (), 1)

def test_profile_identity_is_immutable_and_hashes_canonical_preimage():
    identity = M10ProfileIdentity("embedding", "jira")
    assert len(identity.config_hash) == 64
    forged = object.__new__(M10ProfileIdentity)
    object.__setattr__(forged, "normalized_embedding_profile_text", "embedding")
    with pytest.raises((TypeError, ValueError)):
        M10ProfileIdentity.__post_init__(forged)
    with pytest.raises(M10SnapshotError): M10ProfileIdentity("embedding\r\n", "jira")

@pytest.mark.parametrize("value", [None, object(), ["1"], ("2", "1")])
def test_scope_rejects_wrong_or_noncanonical_pages(value):
    with pytest.raises((TypeError, M10SnapshotError, ValueError)):
        M10ConfluenceScope("src", ("A",), ("1",), value)

def test_metrics_reject_impossible_cross_field_counts():
    with pytest.raises(M10SnapshotError): M10SnapshotMetrics(1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

def test_projection_owns_stream_tuples_and_checks_identity():
    p = M10SnapshotProjection(dataset_name="spen_knowledge_poc", schemas_version="1.0", source_scopes={"confluence": {"source_id": "src", "space_keys": ("A",), "root_page_ids": ("1",), "page_ids": ("1",)}}, generated_at="2026-01-01T00:00:00Z", config_hash="a" * 64, chunker_version=ACTIVE_CHUNKER_VERSION, documents=({"id": "1"},), chunks=(), relations=(), acl=(), media_assets=(), symbols=(), sync_state=(), tombstones=(), metrics=metrics())
    with pytest.raises(AttributeError): p.documents += (2,)
    with pytest.raises(M10SnapshotError): M10SnapshotProjection(dataset_name="bad", schemas_version="1.0", source_scopes={}, generated_at="x", config_hash="a" * 64, chunker_version="v", documents=(), chunks=(), relations=(), acl=(), media_assets=(), symbols=(), sync_state=(), tombstones=(), metrics=metrics())

def test_result_status_matrix_is_closed():
    with pytest.raises(M10SnapshotError): M10SnapshotResult("failed", metrics=metrics())
    with pytest.raises(M10SnapshotError): M10SnapshotResult("composed", metrics=metrics(), digest="a")
    with pytest.raises(M10SnapshotError): M10SnapshotResult("published", metrics=metrics(), digest="a" * 64, dataset_version="v")

def test_quality_input_has_exact_count_algebra():
    q = M10QualityReportInput("p", "active", "v1", {k: 0 for k in ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")}, {}, {}, {}, {}, {}, {}, {}, {})
    assert q.expected_counts["documents"] == 0
    with pytest.raises(M10SnapshotError):
        M10QualityReportInput("p", "active", "v1", {"documents": 0}, {}, {}, {}, {}, {}, {}, {}, {})

@pytest.mark.parametrize("cls,kwargs,missing", [
    (M10ConfluenceScope, {"source_id": "src", "space_keys": ("A",), "root_page_ids": ("1",), "page_ids": ("1",)}, "page_ids"),
    (M10ConfluenceExclusion, {"page_id": "1", "reason": "exclude_page"}, "reason"),
    (M10MediaPolicy, {"include_attachments": False, "allow_download": False, "allowed_processing_statuses": (), "max_assets": 0}, "max_assets"),
])
def test_nested_forged_models_reject_missing_and_extra_fields(cls, kwargs, missing):
    forged = object.__new__(cls)
    for key, value in kwargs.items():
        if key != missing: object.__setattr__(forged, key, value)
    with pytest.raises((TypeError, ValueError)):
        cls.__post_init__(forged)
    object.__setattr__(forged, missing, kwargs[missing]); object.__setattr__(forged, "extra", 1)
    with pytest.raises((TypeError, ValueError)):
        cls.__post_init__(forged)

@pytest.mark.parametrize("stamp", [
    "2026-01-01T00:00:00Z", "2026-01-01T00:00:00.123Z", "2026-01-01T00:00:00+07:00", "2026-01-01T00:00:00.1-04:30",
])
def test_projection_timestamp_accepts_timezone_forms_and_preserves_bytes(stamp):
    p = M10SnapshotProjection(dataset_name="spen_knowledge_poc", schemas_version="1.0", source_scopes={"confluence": {"source_id": "src", "space_keys": ("A",), "root_page_ids": ("1",), "page_ids": ("1",)}}, generated_at=stamp, config_hash="a" * 64, chunker_version=ACTIVE_CHUNKER_VERSION, documents=(), chunks=(), relations=(), acl=(), media_assets=(), symbols=(), sync_state=(), tombstones=(), metrics=M10SnapshotMetrics(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0))
    assert p.generated_at == stamp

@pytest.mark.parametrize("stamp", ["2026-01-01", "2026-01-01T00:00:00", "2026-01-01T00:00:00 utc", "2026-02-30T00:00:00Z", "2026-01-01T00:00:00+0700"])
def test_projection_timestamp_rejects_non_rfc3339(stamp):
    with pytest.raises((TypeError, ValueError)):
        M10SnapshotProjection(dataset_name="spen_knowledge_poc", schemas_version="1.0", source_scopes={"confluence": {"source_id": "src", "space_keys": ("A",), "root_page_ids": ("1",), "page_ids": ("1",)}}, generated_at=stamp, config_hash="a" * 64, chunker_version="v1", documents=(), chunks=(), relations=(), acl=(), media_assets=(), symbols=(), sync_state=(), tombstones=(), metrics=M10SnapshotMetrics(0,0,0,0,0,0,0,0,0,0,0,0,0,0,0))

def test_metrics_result_quality_and_projection_forged_shapes_fail_closed():
    metric = M10SnapshotMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    quality = M10QualityReportInput("p", "active", "v1", {k: 0 for k in ("documents", "chunks", "relations", "acl", "media_assets", "symbols", "sync_state", "tombstones")}, {}, {}, {}, {}, {}, {}, {}, {})
    result = M10SnapshotResult("composed", metric, "a" * 64)
    projection = M10SnapshotProjection(dataset_name="spen_knowledge_poc", schemas_version="1.0", source_scopes={"confluence": {"source_id": "src", "space_keys": ("A",), "root_page_ids": ("1",), "page_ids": ("1",)}}, generated_at="2026-01-01T00:00:00Z", config_hash="a" * 64, chunker_version=ACTIVE_CHUNKER_VERSION, documents=(), chunks=(), relations=(), acl=(), media_assets=(), symbols=(), sync_state=(), tombstones=(), metrics=metric)
    for instance, cls in ((metric, M10SnapshotMetrics), (quality, M10QualityReportInput), (result, M10SnapshotResult), (projection, M10SnapshotProjection)):
        forged = object.__new__(cls)
        for key, value in vars(instance).items(): object.__setattr__(forged, key, value)
        object.__setattr__(forged, "forbidden", True)
        with pytest.raises((TypeError, ValueError)):
            cls.__post_init__(forged)
