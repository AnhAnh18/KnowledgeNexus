from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import IngestionResult
from knowledgenexus.indexing.application.use_cases.ingest_confluence_subtree_from_url import (
    ConfluenceSubtreeIngestError,
    IngestConfluenceSubtreeFromUrl,
)


class _PacketIngestor:
    def __init__(self) -> None:
        self.paths: list[Path] = []
        self.selections: list[object] = []

    async def execute(
        self, packet_path: Path, report_progress=None, include_document_ids=None,
    ) -> IngestionResult:
        self.paths.append(packet_path)
        self.selections.append(include_document_ids)
        if report_progress is not None:
            await report_progress(embedded_chunks=3, total_chunks=3)
        return IngestionResult(
            chunks_ingested=3, chunks_failed=0, source_id="a,b",
            embedding_model="test", status="success",
        )


@pytest.mark.asyncio
async def test_reads_only_the_packet_published_by_foundation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (tmp_path / "snapshots").resolve()
    tokenizer = (tmp_path / "tokenizer").resolve()
    tokenizer.mkdir()
    packet_ingestor = _PacketIngestor()
    calls: list[dict[str, object]] = []
    monkeypatch.delenv("CONFLUENCE_PAT", raising=False)

    def snapshot_run(**kwargs: object) -> dict[str, object]:
        assert os.environ["CONFLUENCE_PAT"] == "test-pat"
        workspace = Path(str(kwargs["output_root"]))
        version = workspace / "versions" / "confluence-test"
        version.mkdir(parents=True)
        (workspace / "LATEST.txt").write_text("confluence-test\n", encoding="ascii")
        callback = kwargs["progress_callback"]
        callback({"phase": "inventory", "requested_pages": 2})
        calls.append(dict(kwargs))
        return {"status": "complete"}

    progress: list[dict[str, object]] = []

    async def report(payload: object) -> None:
        assert type(payload) is dict
        progress.append(dict(payload))

    use_case = IngestConfluenceSubtreeFromUrl(
        snapshot_root=root, tokenizer_assets_dir=tokenizer, max_pages=200,
        confluence_pat="test-pat", packet_ingestor=packet_ingestor, snapshot_run=snapshot_run,
    )
    result = await use_case.execute(
        job_id="job-1", canonical_url="https://example.test/spaces/TEST/pages/1",
        report_progress=report,
    )

    assert result.status == "success"
    assert calls[0]["allow_partial_processing"] is False
    assert packet_ingestor.paths == [root / "job-1" / "versions" / "confluence-test"]
    assert [item["phase"] for item in progress] == [
        # The second "indexing_embed" carries the packet ingestor's periodic
        # counters; embedding is the longest stretch of the job and used to
        # report nothing at all between its start and the final chunk count.
        "inventory", "indexing_validate", "indexing_embed", "indexing_embed",
        "indexing_store",
    ]
    assert progress[3] == {
        "phase": "indexing_embed", "embedded_chunks": 3, "total_chunks": 3,
    }
    assert "CONFLUENCE_PAT" not in os.environ


def test_resume_url_uses_only_durable_context(tmp_path: Path) -> None:
    root = (tmp_path / "snapshots").resolve()
    tokenizer = (tmp_path / "tokenizer").resolve()
    tokenizer.mkdir()
    workspace = root / "job-1"
    workspace.mkdir(parents=True)
    (workspace / "text-snapshot-context.json").write_text(
        json.dumps({
            "base_url": "https://example.test", "space_key": "TEST",
            "root_page_id": "1",
        }), encoding="utf-8",
    )
    use_case = IngestConfluenceSubtreeFromUrl(
        snapshot_root=root, tokenizer_assets_dir=tokenizer, max_pages=200,
        confluence_pat="test-pat", packet_ingestor=_PacketIngestor(),
        snapshot_run=lambda **_: {"status": "complete"},
    )

    assert use_case.resume_url(job_id="job-1") == "https://example.test/spaces/TEST/pages/1"
    with pytest.raises(ConfluenceSubtreeIngestError):
        use_case.resume_url(job_id=object())  # type: ignore[arg-type]


def _publish_documents(workspace: Path, rows: list[dict[str, str]]) -> None:
    version = workspace / "versions" / "confluence-test"
    version.mkdir(parents=True, exist_ok=True)
    (version / "documents.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (workspace / "LATEST.txt").write_text("confluence-test\n", encoding="ascii")


def _row(page_id: str, version: str) -> dict[str, str]:
    return {
        "document_id": f"confluence:page:{page_id}", "page_id": page_id,
        "source_version": version,
    }


@pytest.mark.asyncio
async def test_sync_embeds_only_moved_pages_and_tombstones_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (tmp_path / "snapshots").resolve()
    tokenizer = (tmp_path / "tokenizer").resolve()
    tokenizer.mkdir()
    baseline = root / "baseline"
    _publish_documents(baseline, [_row("1", "v1"), _row("2", "v1"), _row("3", "v1")])
    packet_ingestor = _PacketIngestor()
    monkeypatch.delenv("CONFLUENCE_PAT", raising=False)

    def snapshot_run(**kwargs: object) -> dict[str, object]:
        workspace = Path(str(kwargs["output_root"]))
        # Page 3 is gone at the source, page 1 moved, page 4 is new.
        _publish_documents(workspace, [_row("1", "v2"), _row("2", "v1"), _row("4", "v1")])
        return {"status": "complete"}

    progress: list[dict[str, object]] = []

    async def report(payload: object) -> None:
        assert type(payload) is dict
        progress.append(dict(payload))

    deleted: list[tuple[str, str]] = []

    async def delete_page(page_id: str, document_id: str) -> None:
        deleted.append((page_id, document_id))

    use_case = IngestConfluenceSubtreeFromUrl(
        snapshot_root=root, tokenizer_assets_dir=tokenizer, max_pages=200,
        confluence_pat="test-pat", packet_ingestor=packet_ingestor, snapshot_run=snapshot_run,
    )
    result = await use_case.execute_sync(
        job_id="job-sync", canonical_url="https://example.test/spaces/TEST/pages/1",
        report_progress=report, baseline_workspace=baseline, delete_page=delete_page,
    )

    assert result.plan.new_page_ids == ("4",)
    assert result.plan.changed_page_ids == ("1",)
    assert result.plan.deleted_page_ids == ("3",)
    assert result.plan.unchanged_page_ids == ("2",)
    # A deleted page and a changed page are both purged; an unchanged one is not.
    assert sorted(deleted) == [("1", "confluence:page:1"), ("3", "confluence:page:3")]
    # Only the moved and the new page are handed to the embedder.
    assert packet_ingestor.selections == [
        frozenset({"confluence:page:1", "confluence:page:4"})
    ]
    assert result.stats()["tombstoned_pages"] == 1
    assert {"phase": "sync_plan", "new_pages": 1, "changed_pages": 1,
            "deleted_pages": 1, "unchanged_pages": 1} in progress
    assert {"phase": "tombstone", "purged_pages": 2} in progress


@pytest.mark.asyncio
async def test_sync_without_a_baseline_indexes_the_whole_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = (tmp_path / "snapshots").resolve()
    tokenizer = (tmp_path / "tokenizer").resolve()
    tokenizer.mkdir()
    packet_ingestor = _PacketIngestor()
    monkeypatch.delenv("CONFLUENCE_PAT", raising=False)

    def snapshot_run(**kwargs: object) -> dict[str, object]:
        _publish_documents(Path(str(kwargs["output_root"])), [_row("1", "v1")])
        return {"status": "complete"}

    async def report(payload: object) -> None:
        assert type(payload) is dict

    async def delete_page(page_id: str, document_id: str) -> None:
        raise AssertionError("nothing may be deleted without a baseline")

    use_case = IngestConfluenceSubtreeFromUrl(
        snapshot_root=root, tokenizer_assets_dir=tokenizer, max_pages=200,
        confluence_pat="test-pat", packet_ingestor=packet_ingestor, snapshot_run=snapshot_run,
    )
    result = await use_case.execute_sync(
        job_id="job-first", canonical_url="https://example.test/spaces/TEST/pages/1",
        report_progress=report, baseline_workspace=None, delete_page=delete_page,
    )

    assert result.baseline_found is False
    assert packet_ingestor.selections == [None]
    assert result.plan.new_page_ids == ("1",)
