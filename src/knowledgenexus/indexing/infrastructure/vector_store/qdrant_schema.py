from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams


@dataclass(frozen=True)
class QdrantCollectionConfig:
    collection_name: str
    vector_size: int
    distance: Distance
    payload_indexes: list[dict[str, str]]
    # Hybrid support
    is_hybrid: bool = False
    sparse_name: str = "sparse"
    dense_name: str = "dense"
    rrf_k: int = 60
    prefetch_limit: int = 40


def _parse_distance(value: str) -> Distance:
    mapping = {
        "cosine": Distance.COSINE,
        "euclid": Distance.EUCLID,
        "dot": Distance.DOT,
    }
    return mapping[value.lower()]


def _parse_index_type(value: str) -> PayloadSchemaType:
    mapping = {
        "keyword": PayloadSchemaType.KEYWORD,
        "integer": PayloadSchemaType.INTEGER,
        "float": PayloadSchemaType.FLOAT,
        "datetime": PayloadSchemaType.DATETIME,
        "text": PayloadSchemaType.TEXT,
    }
    return mapping[value.lower()]


def load_qdrant_collection_config(path: Path) -> QdrantCollectionConfig:
    with path.open(encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    vectors = raw["vectors"]

    # Detect hybrid config: vectors is a dict of named vectors
    is_hybrid = isinstance(vectors, dict) and "dense" in vectors

    if is_hybrid:
        dense_cfg = vectors["dense"]
        sparse_cfg = vectors.get("sparse", {})
        retrieval = raw.get("retrieval", {})
        return QdrantCollectionConfig(
            collection_name=raw.get("collection_name", "knowledgenexus"),
            vector_size=int(dense_cfg["size"]),
            distance=_parse_distance(str(dense_cfg["distance"])),
            payload_indexes=list(raw.get("payload_indexes", [])),
            is_hybrid=True,
            sparse_name="sparse",
            dense_name="dense",
            rrf_k=int(retrieval.get("rrf_k", 60)),
            prefetch_limit=int(retrieval.get("prefetch", 40)),
        )

    # Dense-only config (original format)
    return QdrantCollectionConfig(
        collection_name=raw.get("collection_name", "knowledgenexus"),
        vector_size=int(vectors["size"]),
        distance=_parse_distance(str(vectors["distance"])),
        payload_indexes=list(raw.get("payload_indexes", [])),
    )


def index_type_from_config(index_def: dict[str, str]) -> PayloadSchemaType:
    return _parse_index_type(index_def["type"])
