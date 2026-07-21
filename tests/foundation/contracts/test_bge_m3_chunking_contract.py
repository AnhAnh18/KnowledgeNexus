from __future__ import annotations

import json
from pathlib import Path

from knowledgenexus.foundation.infrastructure.config import load_chunking_profile


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "foundation"


def test_chunking_spec_and_profile_lock_the_same_active_identity_and_budget() -> None:
    profile = load_chunking_profile(CONTRACT_ROOT / "embedding_profile.yaml")
    specification = (CONTRACT_ROOT / "CHUNKING_SPEC.md").read_text(encoding="utf-8")

    expected_fragments = (
        "| chunker_version | 1.2.0 |",
        "`BAAI/bge-m3`",
        "| `target_tokens` | 450 |",
        "| `minimum_tokens` | 96 |",
        "| `hard_maximum_tokens` | 1000 |",
        "| `overlap_tokens` | 64 |",
        "| `code_window_target_tokens` | 450 |",
        "| `code_window_max_lines` | 40 |",
        "| `code_window_overlap_lines` | 4 |",
        "provisional_until_benchmark",
    )
    assert all(fragment in specification for fragment in expected_fragments)
    assert profile.chunker_version == "1.2.0"
    assert profile.model_name == profile.tokenizer_name == "BAAI/bge-m3"
    assert "| chunker_version | 1.1.0 |" not in specification
    assert "last normative locked profile (all-MiniLM" not in specification


def test_active_record_schemas_remain_model_agnostic() -> None:
    for filename in (
        "chunk_record.schema.json",
        "defs.schema.json",
        "manifest.schema.json",
    ):
        parsed = json.loads((CONTRACT_ROOT / "schemas" / filename).read_text("utf-8"))
        serialized = json.dumps(parsed, sort_keys=True).lower()
        assert "bge-m3" not in serialized
        assert "minilm" not in serialized
        assert "sentencepiece" not in serialized


def test_start_here_no_longer_lists_bge_m3_migration_as_unapplied() -> None:
    start_here = (CONTRACT_ROOT / "START_HERE.md").read_text(encoding="utf-8")

    assert "CHUNKING_SPEC §1 for bge-m3" not in start_here
    assert "§1 now locks BGE-M3" in start_here
