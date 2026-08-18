"""CLI command to ingest Foundation chunking packets into Qdrant."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import NoReturn, Sequence

from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import (
    IngestChunkingPacket,
    PacketFormatError,
    ChunkTransformationError,
)
from knowledgenexus.indexing.infrastructure.embedding.bge_m3_embedder import BgeM3Embedder
from knowledgenexus.indexing.application.use_cases.chunk_storage_service import ChunkStorageService
from knowledgenexus.indexing.infrastructure.vector_store.qdrant_store import QdrantVectorStore
from knowledgenexus.indexing.infrastructure.repositories.sqlite_chunk_repo import SqliteChunkRepository
from knowledgenexus.indexing.infrastructure.database.engine import create_async_engine
from knowledgenexus.shared.errors import StorageError

CATEGORY_CONFIGURATION = "configuration"
CATEGORY_PACKET_FORMAT = "packet_format"
CATEGORY_TRANSFORMATION = "transformation"
CATEGORY_STORAGE = "storage"
CATEGORY_UNEXPECTED = "unexpected"

EXIT_CONFIGURATION = 2
EXIT_PACKET_FORMAT = 3
EXIT_TRANSFORMATION = 4
EXIT_STORAGE = 5
EXIT_UNEXPECTED = 1


class _ConfigurationError(Exception):
    """A sanitized CLI configuration failure."""


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    try:
        args = _parse_args(argv)
        return asyncio.run(_run(args))
    except SystemExit as exc:
        return int(exc.code or 0)
    except _ConfigurationError:
        return _fail(CATEGORY_CONFIGURATION, EXIT_CONFIGURATION)
    except PacketFormatError as exc:
        return _fail(CATEGORY_PACKET_FORMAT, EXIT_PACKET_FORMAT, detail=str(exc))
    except ChunkTransformationError as exc:
        return _fail(CATEGORY_TRANSFORMATION, EXIT_TRANSFORMATION, detail=str(exc))
    except StorageError as exc:
        return _fail(CATEGORY_STORAGE, EXIT_STORAGE, detail=str(exc))
    except BaseException as exc:
        return _fail(CATEGORY_UNEXPECTED, EXIT_UNEXPECTED, detail=str(exc))


async def _run(args: argparse.Namespace) -> int:
    """Execute the ingestion."""
    packet_path = Path(args.packet_path)
    if not packet_path.exists():
        raise _ConfigurationError

    # Initialize embedder
    embedder = BgeM3Embedder(
        model_name=args.embedding_model,
        device=args.device,
        batch_size=args.batch_size,
        return_sparse=args.hybrid,
    )

    # Initialize database engine and repositories
    engine = await create_async_engine(args.database_url)
    session_factory = engine.get_session_factory()
    chunk_repo = SqliteChunkRepository(session_factory)

    # Initialize Qdrant store
    qdrant_store = await QdrantVectorStore.create(
        url=args.qdrant_url,
        config_path=args.qdrant_config,
        api_key=args.qdrant_api_key,
        collection_name_override=args.collection_name,
    )

    # Create storage service
    storage_service = ChunkStorageService(
        vector_store=qdrant_store,
        chunk_repo=chunk_repo,
    )

    # Execute ingestion
    use_case = IngestChunkingPacket(
        embedder=embedder,
        chunk_storage_service=storage_service,
    )

    result = await use_case.execute(packet_path)

    # Output result
    output = {
        "status": result.status,
        "chunks_ingested": result.chunks_ingested,
        "chunks_failed": result.chunks_failed,
        "source_id": result.source_id,
        "embedding_model": result.embedding_model,
    }
    sys.stdout.write(
        json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )

    # Cleanup
    await qdrant_store.close()
    await engine.dispose()

    return 0 if result.status == "success" else (0 if result.status == "partial" else 1)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Ingest Foundation chunking packets into Qdrant vector store"
    )
    parser.add_argument(
        "packet_path",
        type=str,
        help="Path to Foundation chunking packet directory",
    )
    parser.add_argument(
        "--qdrant-url",
        type=str,
        default="http://localhost:6333",
        help="Qdrant server URL (default: http://localhost:6333)",
    )
    parser.add_argument(
        "--qdrant-config",
        type=str,
        required=True,
        help="Path to Qdrant collection config file",
    )
    parser.add_argument(
        "--qdrant-api-key",
        type=str,
        default=None,
        help="Qdrant API key (optional)",
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default=None,
        help="Override collection name from config",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default="sqlite+aiosqlite:///./chunks.db",
        help="SQLite database URL (default: sqlite+aiosqlite:///./chunks.db)",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="BAAI/bge-m3",
        help="Embedding model name (default: BAAI/bge-m3)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="Device for embedder (cpu or cuda, default: cpu)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for embedding (default: 32)",
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="Enable hybrid search (dense + sparse vectors)",
    )

    return parser.parse_args(argv)


def _fail(category: str, exit_code: int, detail: str = "") -> int:
    """Output failure and return exit code."""
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
