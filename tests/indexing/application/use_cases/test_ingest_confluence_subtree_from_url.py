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

    async def execute(self, packet_path: Path) -> IngestionResult:
        self.paths.append(packet_path)
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
        "inventory", "indexing_validate", "indexing_embed", "indexing_store",
    ]
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
