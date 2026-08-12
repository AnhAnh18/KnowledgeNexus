from pathlib import Path
from dataclasses import replace

import pytest

from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.m10_composition import M10ConfluenceHandoff, M10GitHandoff, compose_m10_projection
from knowledgenexus.foundation.domain.models.m10_snapshot import M10ConfluenceScope, M10MediaPolicy, M10ProfileIdentity, M10SnapshotError, M10SnapshotRequest
from knowledgenexus.foundation.domain.models import m10_snapshot as m10_snapshot_module
from knowledgenexus.foundation.domain.models.chunking_profile import ChunkingProfile, TokenizerAsset
from knowledgenexus.foundation.domain.models.jira_relation_profile import JIRA_EXTRACTION_MODE, JIRA_KEY_PATTERN, JiraRelationProfile
from knowledgenexus.foundation.domain.models.one_page_export import OnePageExportProfileBundle
from knowledgenexus.foundation.domain.models.tombstone_propagation import TombstoneEntityType, TombstoneReason, TombstoneTarget
from knowledgenexus.foundation.domain.rules.tombstone_record_builder import TombstoneRecordBuilder
from tests.fixtures.foundation.record_factories import build_sample_acl_record, build_sample_chunk_record, build_sample_document_record, build_sample_relation_record

RUN = CrawlRunId("123e4567-e89b-42d3-a456-426614174000")
COMMIT = "a" * 40


class NoopValidator:
    def validate_record(self, schema_name, record):
        return None


def _request(tmp_path: Path) -> M10SnapshotRequest:
    revision = "5617a9f61b028005a4858fdac845db406aefb181"
    profile = ChunkingProfile(chunker_version="1.2.0", profile_status="provisional_until_benchmark", active_profile="medium", model_name="BAAI/bge-m3", tokenizer_name="BAAI/bge-m3", tokenizer_family="SentencePiece / XLM-R", vector_dimension=1024, maximum_model_tokens=8192, target_tokens=450, minimum_tokens=96, hard_maximum_tokens=1000, overlap_tokens=64, code_window_target_tokens=450, code_window_max_lines=40, code_window_overlap_lines=4, tokenizer_repository="https://huggingface.co/BAAI/bge-m3", tokenizer_revision=revision, observed_license="MIT", provenance_url=f"https://huggingface.co/BAAI/bge-m3/tree/{revision}", tokenizer_assets=(TokenizerAsset("tokenizer.json", 1, "0" * 64),), transformers_version="4.57.6", tokenizers_version="0.22.2", sentencepiece_version="0.2.2")
    bundle = OnePageExportProfileBundle(chunking_profile=profile, jira_relation_profile=JiraRelationProfile(schema_version=1, extraction_mode=JIRA_EXTRACTION_MODE, key_pattern=JIRA_KEY_PATTERN, allowed_project_keys=("SVMCSPEN",)), normalized_embedding_profile_text="embedding-profile-text", normalized_jira_relation_profile_text="jira-profile-text")
    return M10SnapshotRequest(RUN, RUN, M10ConfluenceScope("src", ("SVMC",), ("123",), ("123",)), (), ("123",), "raw-1", "org-repo", "main", COMMIT, M10MediaPolicy(False, False, (), 0), bundle, "2026-08-05T00:00:00Z", tmp_path, "full_snapshot", M10ProfileIdentity("embedding-profile-text", "jira-profile-text"))


def _handoffs():
    document = build_sample_document_record(); chunk = build_sample_chunk_record(); relation = build_sample_relation_record(); acl = build_sample_acl_record()
    gd = {"schema_version": "1.0", "document_id": "git:file:src-a.py", "source_system": "git", "source_type": "code_file", "title": "a.py", "repo": "org-repo", "branch": "main", "file_path": "src/a.py", "source_version": COMMIT, "content_hash": "b" * 64, "acl_id": "acl:repo:org-repo", "jira_keys": [], "relation_ids": [], "crawled_at": "2026-08-05T00:00:00Z", "metadata": {}}
    gc = {"schema_version": "1.0", "chunk_id": "chunk:git:0123456789abcdef", "document_id": gd["document_id"], "source_system": "git", "source_type": "code_file", "title": "a.py", "text": "print(1)", "content_kind": "code_block", "language": "cpp", "token_count": 2, "heading_path": [], "repo": "org-repo", "branch": "main", "file_path": "src/a.py", "line_start": 1, "line_end": 1, "acl_tags": ["repo:org-repo"], "source_version": COMMIT, "content_hash": "c" * 64, "chunker_version": "1.2.0", "updated_at": None}
    ga = {"schema_version": "1.0", "acl_id": "acl:repo:org-repo", "document_id": gd["document_id"], "source_system": "git", "is_restricted": False, "acl_tags": ["repo:org-repo"], "acl_extraction_status": "ok", "extracted_at": "2026-08-05T00:00:00Z"}
    confluence_sync = {"schema_version": "1.0", "source_id": "src", "entity_id": document["document_id"], "entity_type": "page", "last_seen_version": "1", "last_content_hash": document["content_hash"], "last_synced_at": "2026-08-05T00:00:00Z", "status": "active"}
    git_file_sync = {"schema_version": "1.0", "source_id": "org-repo", "entity_id": gd["document_id"], "entity_type": "file", "last_seen_version": COMMIT, "last_content_hash": gd["content_hash"], "last_synced_at": "2026-08-05T00:00:00Z", "status": "active"}
    git_repo_sync = {"schema_version": "1.0", "source_id": "org-repo", "entity_id": "org-repo", "entity_type": "repo", "last_seen_version": COMMIT, "last_content_hash": None, "last_synced_at": "2026-08-05T00:00:00Z", "status": "active"}
    confluence = M10ConfluenceHandoff(RUN, RUN, "1", (document,), (chunk,), (relation,), (acl,), (), (), (confluence_sync,), "raw-1")
    git = M10GitHandoff("org-repo", "main", COMMIT, (gd,), (gc,), (), (ga,), (), (), (git_file_sync, git_repo_sync))
    return confluence, git


def test_composition_merges_sources_deterministically(tmp_path):
    projection = compose_m10_projection(_request(tmp_path), *_handoffs(), schema_validator=NoopValidator())
    assert tuple(record["document_id"] for record in projection.documents) == ("confluence:page:123", "git:file:src-a.py")
    assert projection.metrics.documents == 2 and projection.tombstones == ()


def test_snapshot_request_rejects_windows_junction_dataset_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = getattr(m10_snapshot_module.os.path, "isjunction", None)

    def isjunction(path: object) -> bool:
        if Path(path) == tmp_path:
            return True
        return bool(original(path)) if callable(original) else False

    monkeypatch.setattr(m10_snapshot_module.os.path, "isjunction", isjunction, raising=False)

    with pytest.raises(M10SnapshotError, match="unsafe dataset_root"):
        _request(tmp_path)


@pytest.mark.parametrize("bad", [None, object(), {"run_id": RUN}])
def test_handoff_rejects_wrong_runtime_types(bad):
    with pytest.raises((TypeError, ValueError, M10SnapshotError)):
        M10ConfluenceHandoff(bad, RUN, "v1", (), (), (), (), (), (), (), "raw")


def test_composition_rejects_provenance_acl_and_duplicate_ids(tmp_path):
    request = _request(tmp_path); confluence, git = _handoffs()
    with pytest.raises(M10SnapshotError): compose_m10_projection(request, M10ConfluenceHandoff(RUN, RUN, "1", confluence.documents, confluence.chunks, confluence.relations, confluence.acl, (), (), (), "other"), git, schema_validator=NoopValidator())
    bad_acl = M10GitHandoff(git.repository, git.branch, git.commit, git.documents, ({**git.chunks[0], "acl_tags": ["repo:other"]},), (), git.acl, (), (), ())
    with pytest.raises(M10SnapshotError): compose_m10_projection(request, confluence, bad_acl, schema_validator=NoopValidator())
    duplicate = M10GitHandoff(git.repository, git.branch, git.commit, ({**git.documents[0], "document_id": "confluence:page:123"},), git.chunks, (), git.acl, (), (), ())
    with pytest.raises(M10SnapshotError): compose_m10_projection(request, confluence, duplicate, schema_validator=NoopValidator())


def test_symbol_requires_exact_git_provenance_and_emitted_chunk(tmp_path):
    confluence, git = _handoffs(); symbol = {"schema_version": "1.0", "symbol_id": "sym:1", "repo": "org-repo", "branch": "main", "commit_hash": COMMIT, "file_path": "src/a.py", "language": "cpp", "symbol_type": "function", "name": "f", "qualified_name": "f", "line_start": 1, "line_end": 2, "chunk_id": "chunk:git:0123456789abcdef", "parse_status": "ok", "scanned_at": "2026-08-05T00:00:00Z"}
    projection = compose_m10_projection(_request(tmp_path), confluence, M10GitHandoff(git.repository, git.branch, git.commit, git.documents, git.chunks, (), git.acl, (), (symbol,), ()), schema_validator=NoopValidator())
    assert projection.metrics.symbols_resolved == 1
    with pytest.raises(M10SnapshotError): compose_m10_projection(_request(tmp_path), confluence, M10GitHandoff(git.repository, git.branch, git.commit, git.documents, git.chunks, (), git.acl, (), ({**symbol, "commit_hash": "b" * 40},), ()), schema_validator=NoopValidator())


def test_media_policy_provenance_and_metrics(tmp_path):
    request = replace(_request(tmp_path), media_policy=M10MediaPolicy(True, False, ("failed", "not_processed", "parsed"), 2))
    confluence, git = _handoffs()
    media = {"schema_version": "1.0", "media_id": "confluence:attachment:1", "parent_document_id": "confluence:page:123", "source_system": "confluence", "filename": "a.txt", "mime_type": "text/plain", "size_bytes": 1, "download_status": "not_attempted", "processing_status": "parsed", "relevance": "high", "extracted_text": None, "summary": None, "confidence": None, "raw_uri": None, "content_hash": None, "source_version": "1", "updated_at": None, "crawled_at": "2026-08-05T00:00:00Z"}
    enriched = M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, confluence.documents, confluence.chunks, confluence.relations, confluence.acl, (media,), confluence.symbols, confluence.sync_state, confluence.raw_artifact_identity)
    projection = compose_m10_projection(request, enriched, git, schema_validator=NoopValidator())
    assert projection.metrics.media_processed == 1 and projection.metrics.media_failed == 0
    with pytest.raises(M10SnapshotError):
        compose_m10_projection(replace(request, media_policy=M10MediaPolicy(True, False, ("failed", "not_processed", "parsed"), 0)), enriched, git, schema_validator=NoopValidator())
    with pytest.raises(M10SnapshotError):
        compose_m10_projection(request, M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, confluence.documents, confluence.chunks, confluence.relations, confluence.acl, ({**media, "content_hash": "d" * 64, "raw_uri": "raw://wrong"},), confluence.symbols, confluence.sync_state, confluence.raw_artifact_identity), git, schema_validator=NoopValidator())


def test_relation_status_and_sync_state_rules(tmp_path):
    request = _request(tmp_path); confluence, git = _handoffs()
    unresolved = {"schema_version": "1.0", "relation_id": "rel:1234567890abcdef", "source_id": "confluence:page:123", "target_id": "jira:issue:SPEN-9999", "relation_type": "mentions_jira_key", "resolution_status": "unresolved_target", "created_at": "2026-08-05T00:00:00Z"}
    documents = ({**confluence.documents[0], "relation_ids": [unresolved["relation_id"]]},)
    chunks = ({**confluence.chunks[0], "relation_ids": [unresolved["relation_id"]]},)
    enriched = M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, documents, chunks, (unresolved,), confluence.acl, (), confluence.symbols, confluence.sync_state, confluence.raw_artifact_identity)
    projection = compose_m10_projection(request, enriched, git, schema_validator=NoopValidator())
    assert projection.metrics.unresolved_relations == 1
    bad_relation = {**unresolved, "target_id": "confluence:page:123"}
    with pytest.raises(M10SnapshotError):
        compose_m10_projection(request, M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, confluence.documents, confluence.chunks, (bad_relation,), confluence.acl, (), confluence.symbols, confluence.sync_state, confluence.raw_artifact_identity), git, schema_validator=NoopValidator())
    sync = {"schema_version": "1.0", "source_id": "src", "entity_id": "confluence:page:123", "entity_type": "page", "last_seen_version": "1", "last_content_hash": None, "last_synced_at": "2026-08-05T00:00:00Z", "status": "active"}
    with_sync = M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, confluence.documents, confluence.chunks, confluence.relations, confluence.acl, (), confluence.symbols, (sync,), confluence.raw_artifact_identity)
    assert compose_m10_projection(request, with_sync, git, schema_validator=NoopValidator()).metrics.sync_state == 3
    with pytest.raises(M10SnapshotError):
        compose_m10_projection(request, M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, confluence.documents, confluence.chunks, confluence.relations, confluence.acl, (), confluence.symbols, ({**sync, "status": "tombstoned"},), confluence.raw_artifact_identity), git, schema_validator=NoopValidator())


def test_relation_must_be_linked_from_its_source_record(tmp_path):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    unlinked = {**confluence.relations[0], "relation_id": "rel:fedcba9876543210"}
    handoff = M10ConfluenceHandoff(
        confluence.run_id,
        confluence.generation_id,
        confluence.source_version,
        confluence.documents,
        confluence.chunks,
        (confluence.relations[0], unlinked),
        confluence.acl,
        (),
        confluence.symbols,
        confluence.sync_state,
        confluence.raw_artifact_identity,
    )
    with pytest.raises(M10SnapshotError, match="relation owner linkage"):
        compose_m10_projection(request, handoff, git, schema_validator=NoopValidator())


@pytest.mark.parametrize("target", ["unknown", "none", "null", "unresolved", " "])
def test_unresolved_relation_placeholders_fail_closed(tmp_path, target):
    request = _request(tmp_path); confluence, git = _handoffs()
    relation = {"schema_version": "1.0", "relation_id": "rel:1234567890abcdef", "source_id": "confluence:page:123", "target_id": target, "relation_type": "embeds_media", "resolution_status": "unresolved_target", "created_at": "2026-08-05T00:00:00Z"}
    handoff = M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, confluence.documents, confluence.chunks, (relation,), confluence.acl, (), confluence.symbols, (), confluence.raw_artifact_identity)
    with pytest.raises(M10SnapshotError): compose_m10_projection(request, handoff, git, schema_validator=NoopValidator())


def test_git_handoff_rejects_cross_source_and_chunk_path_traversal(tmp_path):
    request = _request(tmp_path); confluence, git = _handoffs()
    cross = M10GitHandoff(git.repository, git.branch, git.commit, confluence.documents, git.chunks, (), confluence.acl, (), (), ())
    with pytest.raises(M10SnapshotError): compose_m10_projection(request, confluence, cross, schema_validator=NoopValidator())
    traversal = M10GitHandoff(git.repository, git.branch, git.commit, git.documents, ({**git.chunks[0], "file_path": "../escape"},), (), git.acl, (), (), ())
    with pytest.raises(M10SnapshotError): compose_m10_projection(request, confluence, traversal, schema_validator=NoopValidator())
    backslash = M10GitHandoff(git.repository, git.branch, git.commit, git.documents, ({**git.chunks[0], "file_path": "src\\escape.cpp"},), (), git.acl, (), (), ())
    with pytest.raises(M10SnapshotError): compose_m10_projection(request, confluence, backslash, schema_validator=NoopValidator())


def test_relation_id_closure_rejects_unknown_ids_without_generic_relations(tmp_path):
    request = _request(tmp_path)
    confluence, git = _handoffs()
    # The only relation is a Jira mention, so the old conditional closure
    # check skipped this forged document reference.
    forged_document = {**confluence.documents[0], "relation_ids": ["rel:deadbeefdeadbeef"]}
    forged = M10ConfluenceHandoff(
        confluence.run_id,
        confluence.generation_id,
        confluence.source_version,
        (forged_document,),
        confluence.chunks,
        confluence.relations,
        confluence.acl,
        confluence.media_assets,
        confluence.symbols,
        confluence.sync_state,
        confluence.raw_artifact_identity,
    )
    with pytest.raises(M10SnapshotError):
        compose_m10_projection(request, forged, git, schema_validator=NoopValidator())


def test_tombstone_ownership_requires_git_source_grammar(tmp_path):
    request = replace(_request(tmp_path), export_mode="delta", base_dataset_version="base-1")
    confluence, git = _handoffs()
    schema_validator = NoopValidator()
    wrong_chunk = TombstoneRecordBuilder.build(
        target=TombstoneTarget(TombstoneEntityType.CHUNK, "chunk:confluence:" + "0" * 16),
        reason=TombstoneReason.SOURCE_DELETED,
        detected_at="2026-08-05T00:00:00.000000Z",
        dataset_version="delta-1",
        schema_validator=schema_validator,
    )
    handoff = M10GitHandoff(
        git.repository,
        git.branch,
        git.commit,
        git.documents,
        git.chunks,
        git.relations,
        git.acl,
        git.media_assets,
        git.symbols,
        git.sync_state,
        git.errors,
        (wrong_chunk,),
    )
    with pytest.raises(M10SnapshotError):
        compose_m10_projection(request, confluence, handoff, schema_validator=schema_validator)


def test_git_symbol_tombstone_is_bound_to_repository_and_branch(tmp_path):
    request = replace(_request(tmp_path), export_mode="delta", base_dataset_version="base-1")
    confluence, git = _handoffs()
    wrong_symbol = TombstoneRecordBuilder.build(
        target=TombstoneTarget(TombstoneEntityType.SYMBOL, "other-repo:main:src/a.py:f"),
        reason=TombstoneReason.SOURCE_DELETED,
        detected_at="2026-08-05T00:00:00Z",
        dataset_version="delta-1",
        schema_validator=NoopValidator(),
    )
    handoff = M10GitHandoff(
        git.repository,
        git.branch,
        git.commit,
        git.documents,
        git.chunks,
        git.relations,
        git.acl,
        git.media_assets,
        git.symbols,
        git.sync_state,
        git.errors,
        (wrong_symbol,),
    )
    with pytest.raises(M10SnapshotError):
        compose_m10_projection(request, confluence, handoff, schema_validator=NoopValidator())


def test_git_per_file_acl_tombstone_matches_composition_root_grammar(tmp_path):
    request = replace(_request(tmp_path), export_mode="delta", base_dataset_version="base-1")
    confluence, git = _handoffs()
    acl_id = "acl:repo:org-repo:" + "0" * 16
    document = {**git.documents[0], "acl_id": acl_id}
    acl = {**git.acl[0], "acl_id": acl_id}
    tombstone = TombstoneRecordBuilder.build(
        target=TombstoneTarget(TombstoneEntityType.ACL, acl_id),
        reason=TombstoneReason.CONFIG_INVALIDATED,
        detected_at="2026-08-05T00:00:00.000000Z",
        dataset_version="delta-1",
        schema_validator=NoopValidator(),
    )
    handoff = M10GitHandoff(
        git.repository,
        git.branch,
        git.commit,
        (document,),
        git.chunks,
        git.relations,
        (acl,),
        git.media_assets,
        git.symbols,
        git.sync_state,
        git.errors,
        (tombstone,),
    )
    projection = compose_m10_projection(request, confluence, handoff, schema_validator=NoopValidator())
    assert projection.tombstones[0]["entity_id"] == acl_id
