"""Packet-first bridge from a resolved Confluence root to Indexing.

The Foundation exporter owns crawl, raw evidence, normalization and packet
publication.  Indexing intentionally consumes only its finished packet; it
never receives in-memory chunk records from the crawl path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Awaitable, Callable, Mapping

from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import (
    IngestChunkingPacket,
    IngestionResult,
)
from knowledgenexus.indexing.application.use_cases.confluence_sync_state import (
    SyncPlan,
    build_sync_plan,
    published_packet_dir,
    read_packet_pages,
)
from knowledgenexus.foundation.ports.path_safety import (
    require_plain_directory_chain,
    require_plain_file,
)


@dataclass(frozen=True)
class SubtreeSyncResult:
    """What one sync run actually did to the index."""

    ingestion: IngestionResult
    plan: SyncPlan
    deleted_pages: int
    baseline_found: bool
    reused_pages: int = 0

    def stats(self) -> dict[str, int | bool]:
        return {
            **self.plan.counts(),
            "tombstoned_pages": self.deleted_pages,
            "chunks_ingested": self.ingestion.chunks_ingested,
            "chunks_failed": self.ingestion.chunks_failed,
            "baseline_found": self.baseline_found,
            # Unchanged pages served from baseline raw evidence instead of a
            # network re-fetch. Equal to the unchanged count when the baseline
            # raw store is intact.
            "reused_pages": self.reused_pages,
        }


class ConfluenceSubtreeIngestError(Exception):
    def __init__(self, category: str, *, resumable: bool) -> None:
        super().__init__()
        self.category = category
        self.resumable = resumable


logger = logging.getLogger(__name__)

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
        """Publish the packet for a root and ingest all of it."""
        packet_dir = await self._publish_packet(
            job_id=job_id, canonical_url=canonical_url, report_progress=report_progress,
        )
        return await self._ingest_packet(
            packet_dir, report_progress=report_progress, include_document_ids=None,
        )

    async def _publish_packet(
        self, *, job_id: str, canonical_url: str, report_progress: ProgressReporter,
        reuse_baseline: dict[str, object] | None = None,
    ) -> Path:
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
                            reuse_baseline=reuse_baseline,
                        )
                    finally:
                        if prior_pat is None:
                            os.environ.pop("CONFLUENCE_PAT", None)
                        else:
                            os.environ["CONFLUENCE_PAT"] = prior_pat
            except Exception as exc:
                category = getattr(exc, "category", "foundation")
                # `from None` keeps the operator-facing category clean, but it
                # also threw the only description of what actually broke -- a
                # phase failure surfaced as a bare category with no trace
                # anywhere. Log the cause before dropping it.
                logger.exception(
                    "Foundation phase failed for ingest job %s (category=%s)",
                    job_id, category,
                )
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
        return packet_dir

    async def _ingest_packet(
        self, packet_dir: Path, *, report_progress: ProgressReporter,
        include_document_ids: frozenset[str] | None,
    ) -> IngestionResult:
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

            ingestion = await self._packet_ingestor.execute(
                packet_dir, report_embedding, include_document_ids=include_document_ids,
            )
        except Exception as exc:
            category = "indexing"
            raise ConfluenceSubtreeIngestError(category, resumable=True) from None
        if ingestion.status != "success" or ingestion.chunks_failed != 0:
            raise ConfluenceSubtreeIngestError("indexing_partial", resumable=True)
        await report_progress({
            "phase": "indexing_store", "chunks_ingested": ingestion.chunks_ingested,
        })
        return ingestion

    def _reuse_baseline(self, baseline_workspace: Path | None) -> dict[str, object] | None:
        """Describe the baseline raw evidence the capture phase may reuse.

        Returns ``None`` unless the baseline has a published packet: the capture
        phase only reuses a page whose version still matches, so passing the
        full baseline version map is safe -- changed and vanished pages simply
        fall through to a live fetch.
        """
        if baseline_workspace is None:
            return None
        packet = published_packet_dir(baseline_workspace)
        if packet is None:
            return None
        # Version name is ``confluence-<run_id>`` by construction; the run id is
        # what keys the raw store the unchanged bodies live in.
        run_id = packet.name.removeprefix("confluence-")
        pages = read_packet_pages(baseline_workspace)
        if not run_id or not pages:
            return None
        return {
            "raw_root": str(baseline_workspace / ".raw"),
            "run_id": run_id,
            "versions": {page_id: state.source_version for page_id, state in pages.items()},
        }

    async def execute_sync(
        self, *, job_id: str, canonical_url: str, report_progress: ProgressReporter,
        baseline_workspace: Path | None,
        delete_page: Callable[[str, str], Awaitable[None]],
    ) -> SubtreeSyncResult:
        """Re-publish a root and reconcile the index against the last packet.

        The capture contract binds a run to the whole inventory it crawled, so
        the pipeline still *lists* and *processes* the entire subtree.  What a
        sync avoids is the two most expensive parts: embedding (only pages whose
        ``source_version`` moved, plus new pages, are embedded and stored) and,
        when a baseline is present, the *network fetch* of unchanged page
        bodies -- those are served from the baseline's raw evidence via
        ``reuse_baseline`` instead of being re-fetched.

        Pages that vanished from the source are tombstoned: their chunks,
        vectors and document row are deleted, which a plain re-ingest can
        never do because a packet only describes what still exists.

        Changed pages are purged before their replacement is written, because
        a shorter revision leaves chunks behind that nothing would otherwise
        remove.  If the job dies in that window those pages are missing from
        the index until it is resumed -- the packet is already published by
        then, so a resume skips the crawl and only repeats the indexing.
        """
        reuse_baseline = self._reuse_baseline(baseline_workspace)
        packet_dir = await self._publish_packet(
            job_id=job_id, canonical_url=canonical_url, report_progress=report_progress,
            reuse_baseline=reuse_baseline,
        )
        workspace = self._snapshot_root / job_id
        current = read_packet_pages(workspace)
        baseline = read_packet_pages(baseline_workspace) if baseline_workspace else {}
        plan = build_sync_plan(baseline=baseline, current=current)
        await report_progress({"phase": "sync_plan", **plan.counts()})
        # With no baseline there is nothing to diff against and nothing to
        # tombstone: this is a first ingest wearing a sync's clothes, so index
        # the whole packet rather than silently indexing nothing.
        if not baseline:
            ingestion = await self._ingest_packet(
                packet_dir, report_progress=report_progress, include_document_ids=None,
            )
            return SubtreeSyncResult(
                ingestion=ingestion, plan=plan, deleted_pages=0, baseline_found=False,
            )
        purged = (*plan.deleted_page_ids, *plan.changed_page_ids)
        if purged:
            await report_progress({"phase": "tombstone", "purged_pages": len(purged)})
            for page_id in purged:
                # A deleted page only exists in the baseline; a changed one is
                # in both and carries the same document id either way.
                state = current.get(page_id) or baseline[page_id]
                await delete_page(page_id, state.document_id)
        include = frozenset(
            current[page_id].document_id for page_id in plan.touched_page_ids
        )
        ingestion = await self._ingest_packet(
            packet_dir, report_progress=report_progress, include_document_ids=include,
        )
        return SubtreeSyncResult(
            ingestion=ingestion, plan=plan,
            deleted_pages=len(plan.deleted_page_ids), baseline_found=True,
            # Reuse applies exactly to the pages present in both at the same
            # version; when the baseline raw store is intact this is the count
            # of network fetches avoided.
            reused_pages=len(plan.unchanged_page_ids) if reuse_baseline else 0,
        )
