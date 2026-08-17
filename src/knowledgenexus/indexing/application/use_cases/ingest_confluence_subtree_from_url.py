"""Packet-first bridge from a resolved Confluence root to Indexing.

The Foundation exporter owns crawl, raw evidence, normalization and packet
publication.  Indexing intentionally consumes only its finished packet; it
never receives in-memory chunk records from the crawl path.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from threading import Lock
from typing import Awaitable, Callable, Mapping

from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import (
    IngestChunkingPacket,
    IngestionResult,
)
from knowledgenexus.foundation.ports.path_safety import (
    require_plain_directory_chain,
    require_plain_file,
)


class ConfluenceSubtreeIngestError(Exception):
    def __init__(self, category: str, *, resumable: bool) -> None:
        super().__init__()
        self.category = category
        self.resumable = resumable


ProgressReporter = Callable[[Mapping[str, object]], Awaitable[None]]

# The approved Foundation subtree operator consumes credentials through
# process environment variables. Serialize this bridge so concurrent jobs
# cannot observe each other's temporary credential environment.
_FOUNDATION_ENVIRONMENT_LOCK = Lock()


class IngestConfluenceSubtreeFromUrl:
    def __init__(
        self,
        *,
        snapshot_root: Path,
        tokenizer_assets_dir: Path,
        max_pages: int,
        confluence_pat: str,
        packet_ingestor: IngestChunkingPacket,
        snapshot_run: Callable[..., dict[str, object]] | None = None,
    ) -> None:
        if not snapshot_root.is_absolute() or not tokenizer_assets_dir.is_absolute():
            raise ValueError("subtree paths must be absolute")
        if type(max_pages) is not int or max_pages <= 0 or max_pages > 5_000:
            raise ValueError("max_pages is invalid")
        if type(confluence_pat) is not str or not confluence_pat:
            raise ValueError("Confluence PAT is invalid")
        self._snapshot_root = snapshot_root
        self._tokenizer_assets_dir = tokenizer_assets_dir
        self._max_pages = max_pages
        self._confluence_pat = confluence_pat
        self._packet_ingestor = packet_ingestor
        self._snapshot_run = snapshot_run

    def resume_url(self, *, job_id: str) -> str:
        """Recover only the canonical root identity from the durable workspace."""
        if type(job_id) is not str or not job_id:
            raise ConfluenceSubtreeIngestError("job", resumable=False)
        context = self._snapshot_root / job_id / "text-snapshot-context.json"
        try:
            require_plain_directory_chain(context.parent)
            require_plain_file(context)
            payload = json.loads(context.read_text(encoding="utf-8"))
            base_url = payload["base_url"]
            space_key = payload["space_key"]
            page_id = payload["root_page_id"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            raise ConfluenceSubtreeIngestError("resume_context", resumable=False) from None
        if not all(type(value) is str and value for value in (base_url, space_key, page_id)):
            raise ConfluenceSubtreeIngestError("resume_context", resumable=False)
        return f"{base_url}/spaces/{space_key}/pages/{page_id}"

    async def execute(
        self, *, job_id: str, canonical_url: str, report_progress: ProgressReporter
    ) -> IngestionResult:
        if type(job_id) is not str or not job_id:
            raise ConfluenceSubtreeIngestError("job", resumable=False)
        workspace = self._snapshot_root / job_id
        loop = asyncio.get_running_loop()

        def report_from_worker(payload: Mapping[str, object]) -> None:
            future = asyncio.run_coroutine_threadsafe(report_progress(payload), loop)
            future.result()

        def run_foundation() -> dict[str, object]:
            runner = self._snapshot_run
            if runner is None:
                # The CLI currently hosts the approved demo orchestration.  It
                # is called as a typed function, never as a PowerShell/process
                # subprocess, and its public run boundary is the only bridge.
                from knowledgenexus.foundation.cli.export_confluence_url_text_snapshot import run
                runner = run
            try:
                with _FOUNDATION_ENVIRONMENT_LOCK:
                    prior_pat = os.environ.get("CONFLUENCE_PAT")
                    try:
                        os.environ["CONFLUENCE_PAT"] = self._confluence_pat
                        return runner(
                            url=canonical_url,
                            output_root=str(workspace),
                            tokenizer_assets_dir=str(self._tokenizer_assets_dir),
                            max_pages=self._max_pages,
                            allow_partial_processing=False,
                            progress_callback=report_from_worker,
                        )
                    finally:
                        if prior_pat is None:
                            os.environ.pop("CONFLUENCE_PAT", None)
                        else:
                            os.environ["CONFLUENCE_PAT"] = prior_pat
            except Exception as exc:
                category = getattr(exc, "category", "foundation")
                raise ConfluenceSubtreeIngestError(
                    category if type(category) is str else "foundation", resumable=True
                ) from None

        result = await asyncio.to_thread(run_foundation)
        if type(result) is not dict or result.get("status") != "complete":
            raise ConfluenceSubtreeIngestError("foundation", resumable=True)
        latest = workspace / "LATEST.txt"
        try:
            require_plain_directory_chain(workspace)
            require_plain_file(latest)
            version_name = latest.read_text(encoding="ascii").strip()
            if (
                not version_name.startswith("confluence-")
                or Path(version_name).name != version_name
            ):
                raise ValueError
            packet_dir = workspace / "versions" / version_name
            require_plain_directory_chain(packet_dir)
        except (OSError, UnicodeDecodeError, ValueError):
            raise ConfluenceSubtreeIngestError("publication", resumable=True) from None
        await report_progress({"phase": "indexing_validate"})
        try:
            await report_progress({"phase": "indexing_embed"})

            async def report_embedding(*, embedded_chunks: int, total_chunks: int) -> None:
                # Embedding a packet is typically the longest stretch of the job
                # and used to report nothing between "indexing_embed" and the
                # final count, so the UI looked stalled for the whole of it.
                await report_progress({
                    "phase": "indexing_embed",
                    "embedded_chunks": embedded_chunks,
                    "total_chunks": total_chunks,
                })

            ingestion = await self._packet_ingestor.execute(packet_dir, report_embedding)
        except Exception as exc:
            category = "indexing"
            raise ConfluenceSubtreeIngestError(category, resumable=True) from None
        if ingestion.status != "success" or ingestion.chunks_failed != 0:
            raise ConfluenceSubtreeIngestError("indexing_partial", resumable=True)
        await report_progress({
            "phase": "indexing_store", "chunks_ingested": ingestion.chunks_ingested,
        })
        return ingestion
