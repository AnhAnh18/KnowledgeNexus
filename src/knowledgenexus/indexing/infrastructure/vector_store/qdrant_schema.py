from dataclasses import dataclass
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
    return QdrantCollectionConfig(
        collection_name=raw.get("collection_name", "knowledgenexus"),
        vector_size=int(vectors["size"]),
        distance=_parse_distance(str(vectors["distance"])),
        payload_indexes=list(raw.get("payload_indexes", [])),
    )


def index_type_from_config(index_def: dict[str, str]) -> PayloadSchemaType:
    return _parse_index_type(index_def["type"])
