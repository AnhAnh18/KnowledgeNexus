from pathlib import Path

import pytest
from qdrant_client.models import Distance, PayloadSchemaType

from knowledgenexus.indexing.infrastructure.vector_store.qdrant_schema import (
    QdrantCollectionConfig,
    index_type_from_config,
    load_qdrant_collection_config,
)


def test_load_qdrant_collection_config_from_project_yaml(project_root: Path):
    config = load_qdrant_collection_config(project_root / "config" / "qdrant.collection.yaml")

    assert config.collection_name == "knowledgenexus"
    assert config.vector_size == 1024
    assert config.distance == Distance.COSINE
    assert len(config.payload_indexes) == 5
    assert config.payload_indexes[0] == {"field": "source_type", "type": "keyword"}


def test_load_qdrant_collection_config_defaults(tmp_path: Path):
    yaml_path = tmp_path / "collection.yaml"
    yaml_path.write_text(
        """
vectors:
  size: 256
  distance: euclid
""",
        encoding="utf-8",
    )

    config = load_qdrant_collection_config(yaml_path)

    assert config.collection_name == "knowledgenexus"
    assert config.vector_size == 256
    assert config.distance == Distance.EUCLID
    assert config.payload_indexes == []


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        ("cosine", Distance.COSINE),
        ("Cosine", Distance.COSINE),
        ("euclid", Distance.EUCLID),
        ("dot", Distance.DOT),
    ],
)
def test_parse_distance(distance: str, expected: Distance, tmp_path: Path):
    yaml_path = tmp_path / "collection.yaml"
    yaml_path.write_text(
        f"""
vectors:
  size: 8
  distance: {distance}
""",
        encoding="utf-8",
    )

    config = load_qdrant_collection_config(yaml_path)
    assert config.distance == expected


@pytest.mark.parametrize(
    ("index_type", "expected"),
    [
        ("keyword", PayloadSchemaType.KEYWORD),
        ("integer", PayloadSchemaType.INTEGER),
        ("float", PayloadSchemaType.FLOAT),
        ("datetime", PayloadSchemaType.DATETIME),
        ("text", PayloadSchemaType.TEXT),
    ],
)
def test_index_type_from_config(index_type: str, expected: PayloadSchemaType):
    assert index_type_from_config({"field": "x", "type": index_type}) == expected


def test_qdrant_collection_config_is_frozen():
    config = QdrantCollectionConfig(
        collection_name="c",
        vector_size=8,
        distance=Distance.COSINE,
        payload_indexes=[],
    )
    with pytest.raises(AttributeError):
        config.collection_name = "other"  # type: ignore[misc]
