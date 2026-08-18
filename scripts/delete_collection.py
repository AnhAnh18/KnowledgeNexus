#!/usr/bin/env python3
"""Delete a Qdrant collection.

Usage:
    python scripts/delete_collection.py --name knowledgenexus_dense_test
    python scripts/delete_collection.py --name knowledgenexus_hybrid_test
"""
from __future__ import annotations

import argparse
import asyncio

from qdrant_client import AsyncQdrantClient


async def delete_collection(
    name: str,
    qdrant_url: str,
    api_key: str | None = None,
) -> None:
    client = AsyncQdrantClient(url=qdrant_url, api_key=api_key)

    collections = await client.get_collections()
    existing = {c.name for c in collections.collections}

    if name not in existing:
        print(f"Collection '{name}' does not exist. Nothing to delete.")
        await client.close()
        return

    await client.delete_collection(name)
    print(f"[OK] Deleted collection '{name}'")
    await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete a Qdrant collection")
    parser.add_argument(
        "--name",
        required=True,
        help="Collection name to delete",
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
        delete_collection(
            name=args.name,
            qdrant_url=args.qdrant_url,
            api_key=args.api_key,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
