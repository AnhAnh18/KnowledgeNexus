#!/usr/bin/env python3
"""Create a Qdrant collection from a config file.

Usage:
    python scripts/create_collection.py --config config/qdrant.collection.yaml
    python scripts/create_collection.py --config config/qdrant.collection.hybrid.yaml
    python scripts/create_collection.py --config config/qdrant.collection.yaml --name my_collection
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import VectorParams, SparseVectorParams

from knowledgenexus.indexing.infrastructure.vector_store.qdrant_schema import (
    load_qdrant_collection_config,
    index_type_from_config,
)


async def create_collection(
    config_path: str,
    qdrant_url: str,
    api_key: str | None = None,
    name_override: str | None = None,
) -> None:
    config = load_qdrant_collection_config(Path(config_path))
    collection_name = name_override or config.collection_name

    client = AsyncQdrantClient(url=qdrant_url, api_key=api_key)

    # Check if collection already exists
    collections = await client.get_collections()
    existing = {c.name for c in collections.collections}

    if collection_name in existing:
        print(f"Collection '{collection_name}' already exists. Deleting first...")
        await client.delete_collection(collection_name)

    # Create collection
    if config.is_hybrid:
        print(f"Creating hybrid collection '{collection_name}' (dense + sparse)...")
        dense_params = VectorParams(
            size=config.vector_size,
            distance=config.distance,
        )
        sparse_params = SparseVectorParams()
        await client.create_collection(
            collection_name=collection_name,
            vectors_config={
                config.dense_name: dense_params,
            },
            sparse_vectors_config={
                config.sparse_name: sparse_params,
            },
        )
    else:
        print(f"Creating dense collection '{collection_name}'...")
        await client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=config.vector_size,
                distance=config.distance,
            ),
        )

    # Create payload indexes
    for index_def in config.payload_indexes:
        try:
            await client.create_payload_index(
                collection_name=collection_name,
                field_name=index_def["field"],
                field_schema=index_type_from_config(index_def),
            )
            print(f"  Index: {index_def['field']} ({index_def['type']})")
        except Exception as e:
            print(f"  Index {index_def['field']} skipped: {e}")

    # Verify
    info = await client.get_collection(collection_name)
    print(f"\n[OK] Collection '{collection_name}' created:")
    print(f"   Points: {info.points_count}")
    print(f"   Vectors: {info.config.params.vectors}")
    print(f"   Hybrid: {config.is_hybrid}")

    await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Qdrant collection")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to collection config YAML",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Override collection name",
    )
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6333",
        help="Qdrant URL (default: http://localhost:6333)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Qdrant API key (optional)",
    )
    args = parser.parse_args()

    asyncio.run(
        create_collection(
            config_path=args.config,
            qdrant_url=args.qdrant_url,
            api_key=args.api_key,
            name_override=args.name,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
