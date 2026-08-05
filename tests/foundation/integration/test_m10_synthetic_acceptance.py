from __future__ import annotations

import hashlib
from dataclasses import replace

from knowledgenexus.foundation.infrastructure.exporters.m10_snapshot_exporter import M10FullSnapshotExporter
from knowledgenexus.foundation.domain.models.m10_composition import M10ConfluenceHandoff, M10GitHandoff
from knowledgenexus.foundation.domain.models.m10_snapshot import M10MediaPolicy
from tests.foundation.domain.models.test_m10_composition import _handoffs, _request


class _Adapter:
    def __init__(self, value):
        self.value = value

    def collect(self, request):
        return self.value


def _extended(tmp_path):
    request = replace(_request(tmp_path), media_policy=M10MediaPolicy(True, False, ("failed", "not_processed", "parsed"), 1))
    confluence, git = _handoffs()
    stamp = "2026-08-05T00:00:00Z"
    media = {
        "schema_version": "1.0", "media_id": "confluence:attachment:1", "parent_document_id": "confluence:page:123",
        "source_system": "confluence", "filename": "diagram.drawio", "mime_type": "application/xml", "size_bytes": 1,
        "download_status": "not_attempted", "processing_status": "parsed", "relevance": "high", "extracted_text": "node",
        "summary": None, "confidence": None, "raw_uri": None, "content_hash": None, "source_version": "1", "updated_at": None, "crawled_at": stamp,
    }
    page_sync = {"schema_version": "1.0", "source_id": "src", "entity_id": "confluence:page:123", "entity_type": "page", "last_seen_version": "1", "last_content_hash": None, "last_synced_at": stamp, "status": "active"}
    attachment_sync = {**page_sync, "entity_id": "confluence:attachment:1", "entity_type": "attachment"}
    symbol = {
        "schema_version": "1.0", "symbol_id": "sym:org-repo:src-a.py:f", "repo": "org-repo", "branch": "main", "commit_hash": request.git_commit,
        "file_path": "src/a.py", "language": "cpp", "symbol_type": "function", "name": "f", "qualified_name": "f", "signature": None,
        "line_start": 1, "line_end": 1, "parent_symbol": None, "chunk_id": git.chunks[0]["chunk_id"], "parse_status": "ok", "scanned_at": stamp,
    }
    file_sync = {"schema_version": "1.0", "source_id": "org-repo", "entity_id": git.documents[0]["document_id"], "entity_type": "file", "last_seen_version": request.git_commit, "last_content_hash": None, "last_synced_at": stamp, "status": "active"}
    repo_sync = {"schema_version": "1.0", "source_id": "org-repo", "entity_id": "org-repo", "entity_type": "repo", "last_seen_version": request.git_commit, "last_content_hash": None, "last_synced_at": stamp, "status": "active"}
    confluence = M10ConfluenceHandoff(confluence.run_id, confluence.generation_id, confluence.source_version, confluence.documents, confluence.chunks, confluence.relations, confluence.acl, (media,), (), (page_sync, attachment_sync), confluence.raw_artifact_identity)
    git = M10GitHandoff(git.repository, git.branch, git.commit, git.documents, git.chunks, (), git.acl, (), (symbol,), (file_sync, repo_sync))
    return request, confluence, git


def test_two_equivalent_exports_have_identical_ten_file_bytes(tmp_path):
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    first_root.mkdir(); second_root.mkdir()
    first_request, first_confluence, first_git = _extended(first_root)
    second_request, second_confluence, second_git = _extended(second_root)
    first = M10FullSnapshotExporter(confluence_adapter=_Adapter(first_confluence), git_adapter=_Adapter(first_git)).execute(first_request)
    second = M10FullSnapshotExporter(confluence_adapter=_Adapter(second_confluence), git_adapter=_Adapter(second_git)).execute(second_request)
    assert first.dataset_version == second.dataset_version
    first_files = {path.name: path.read_bytes() for path in first.final_path.iterdir()}
    second_files = {path.name: path.read_bytes() for path in second.final_path.iterdir()}
    assert first_files == second_files
    assert hashlib.sha256(first_files["quality_report.md"]).hexdigest() not in first_files["quality_report.md"].decode()
    assert (first_root / "LATEST.txt").read_bytes() == (second_root / "LATEST.txt").read_bytes()
