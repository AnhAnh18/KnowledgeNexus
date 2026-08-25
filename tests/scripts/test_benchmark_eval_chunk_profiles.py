from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "benchmark_eval_chunk_profiles.py"
_SPEC = importlib.util.spec_from_file_location("benchmark_eval_chunk_profiles", _SCRIPT)
assert _SPEC and _SPEC.loader
benchmark = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = benchmark
_SPEC.loader.exec_module(benchmark)


def test_chunk_text_uses_overlap_and_respects_target() -> None:
    text = " ".join(f"term{i}" for i in range(10))
    chunks = benchmark.chunk_text(
        text,
        target_tokens=4,
        overlap_tokens=1,
        counter=benchmark.WhitespaceTokenCounter(),
    )
    assert [len(benchmark.WhitespaceTokenCounter().spans(chunk)) for chunk in chunks] == [4, 4, 4]
    assert chunks[0].split()[-1] == chunks[1].split()[0]


def test_benchmark_reports_structural_metrics(tmp_path: Path) -> None:
    (tmp_path / "one.md").write_text("one two three four five", encoding="utf-8")
    report = benchmark.benchmark(
        tmp_path,
        {
            "small": {"target_tokens": 3, "overlap_tokens": 1},
            "large": {"target_tokens": 10, "overlap_tokens": 1},
        },
        benchmark.WhitespaceTokenCounter(),
    )
    assert report["documents"] == 1
    result = report["profiles"]["small"]
    assert result["chunks_total"] == 2
    assert result["duplicate_token_ratio"] == 0.2
    assert report["warning"] is None
