from __future__ import annotations

import json
from pathlib import Path


def test_foundation_producer_matrix_covers_all_m10_streams() -> None:
    root = Path(__file__).parents[3]
    matrix = json.loads((root / "docs" / "FOUNDATION_PRODUCER_MATRIX.json").read_text(encoding="utf-8"))
    names = {row["name"] for row in matrix["streams"]}
    assert names == {
        "documents", "chunks", "relations", "acl",
        "media_assets", "symbols", "sync_state", "tombstones",
    }
    assert all(row["schema"] and row["producers"] and row["closure"] for row in matrix["streams"])
    assert set(matrix["gates"]) >= {"schema-valid", "cross-stream-closed", "readback-accepted"}


def test_foundation_producer_matrix_rejects_duplicate_stream_rows() -> None:
    root = Path(__file__).parents[3]
    matrix = json.loads((root / "docs" / "FOUNDATION_PRODUCER_MATRIX.json").read_text(encoding="utf-8"))
    names = [row["name"] for row in matrix["streams"]]
    assert len(names) == len(set(names))
