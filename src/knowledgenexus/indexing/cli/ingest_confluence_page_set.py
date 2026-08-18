"""CLI: chunk a Confluence mini corpus and ingest it directly into storage.

Unlike `export_confluence_mini_corpus_indexing_packet.py` (which writes
chunks.jsonl/documents.jsonl to disk for offline smoke testing),
this command runs Foundation chunking and feeds the resulting
ChunkRecords straight into embedding + Qdrant + SQLite storage via
`IngestChunkingPacket.execute_records()` — no intermediate JSON file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import NoReturn, Sequence

from knowledgenexus.foundation.application.use_cases.process_confluence_page_set import (
    ProcessConfluencePageSet,
)
from knowledgenexus.foundation.cli.accept_confluence_mini_corpus import (
    MiniCorpusOperatorInputError,
    load_mini_corpus_selection,
    safe_mini_corpus_path,
)
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_page_set import (
    ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    ConfluencePageSetError,
    ConfluencePageSetRequest,
)
from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import (
    load_chunking_profile,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import (
    ChunkTransformationError,
    IngestChunkingPacket,
    PacketFormatError,
)
from knowledgenexus.shared.config.settings import Settings
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from knowledgenexus.shared.di.container import build_container
from knowledgenexus.shared.errors import StorageError

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_CHUNKING = "chunking"
CATEGORY_TRANSFORMATION = "transformation"
CATEGORY_STORAGE = "storage"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_CONFIGURATION = 2
EXIT_CHUNKING = 3
EXIT_TRANSFORMATION = 4
EXIT_STORAGE = 5
EXIT_UNEXPECTED = 1


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    try:
        args = _parse_args(argv)
        return asyncio.run(_run(args))
    except SystemExit as exc:
        return int(exc.code or 0)
    except MiniCorpusOperatorInputError:
        return _fail(CATEGORY_CONFIGURATION, EXIT_CONFIGURATION)
    except ConfluencePageSetError as exc:
        return _fail(CATEGORY_CHUNKING, EXIT_CHUNKING, detail=exc.category.value)
    except PacketFormatError as exc:
        return _fail(CATEGORY_CHUNKING, EXIT_CHUNKING, detail=str(exc))
    except ChunkTransformationError as exc:
        return _fail(CATEGORY_TRANSFORMATION, EXIT_TRANSFORMATION, detail=str(exc))
    except StorageError as exc:
        return _fail(CATEGORY_STORAGE, EXIT_STORAGE, detail=str(exc))
    except BaseException as exc:
        return _fail(CATEGORY_UNEXPECTED, EXIT_UNEXPECTED, detail=str(exc))


async def _run(args: argparse.Namespace) -> int:
    raw_root = safe_mini_corpus_path(args.data_root)
    selection_path = safe_mini_corpus_path(args.selection_path)
    profile_path = safe_mini_corpus_path(args.profile_path)
    tokenizer_assets_dir = safe_mini_corpus_path(args.tokenizer_assets_dir)
    if (
        not raw_root.is_dir()
        or not selection_path.is_file()
        or not profile_path.is_file()
        or not tokenizer_assets_dir.is_dir()
    ):
        raise MiniCorpusOperatorInputError

    run_id = CrawlRunId(args.run_id)
    items = load_mini_corpus_selection(selection_path)
    request = ConfluencePageSetRequest(
        run_id=run_id,
        generation_id=run_id,
        items=items,
        profile_identity=ACTIVE_PAGE_SET_PROFILE_IDENTITY,
    )
    profile = load_chunking_profile(profile_path)
    tokenizer = BgeM3LocalTokenizer(
        profile=profile,
        tokenizer_assets_dir=tokenizer_assets_dir,
    )
    validator = FoundationSchemaValidator()

    result = ProcessConfluencePageSet(
        chunking_profile=profile,
        tokenizer=tokenizer,
        raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root),
        raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
        storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
        schema_validator=validator,
    ).execute(request=request)

    container = await build_container(Settings())
    try:
        use_case = IngestChunkingPacket(
            embedder=container.get_embedder(),
            chunk_storage_service=container.chunk_storage,
        )
        ingestion_result = await use_case.execute_records(
            [dict(record) for record in result.chunks],
            [dict(document) for document in result.documents],
        )
    finally:
        await container.shutdown()

    output = {
        "status": ingestion_result.status,
        "chunks_ingested": ingestion_result.chunks_ingested,
        "chunks_failed": ingestion_result.chunks_failed,
        "source_id": ingestion_result.source_id,
        "embedding_model": ingestion_result.embedding_model,
        "documents_chunked": result.metrics.document_count,
        "chunks_chunked": result.metrics.chunk_count,
    }
    sys.stdout.write(
        json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )

    return 0 if ingestion_result.status in ("success", "partial") else 1


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SanitizedParser(
        description=(
            "Chunk a Confluence mini corpus with Foundation and ingest the "
            "resulting ChunkRecords directly into Qdrant + SQLite (no "
            "intermediate packet file)."
        )
    )
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--selection-path", required=True)
    parser.add_argument("--profile-path", required=True)
    parser.add_argument("--tokenizer-assets-dir", required=True)
    return parser.parse_args(argv)


class _SanitizedParser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise MiniCorpusOperatorInputError


def _fail(category: str, exit_code: int, detail: str = "") -> int:
    output = {
        "status": "error",
        "category": category,
        "detail": detail,
    }
    sys.stderr.write(
        json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
