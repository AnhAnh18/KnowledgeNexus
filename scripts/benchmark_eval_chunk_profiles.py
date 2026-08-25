"""Compare configured chunk budgets against the committed eval corpus.

This is a deterministic, offline structural benchmark. It intentionally does
not score retrieval: the bundled golden labels identify source documents, not
the exact evidence chunks needed to make a chunk-level relevance judgement.
Pass ``--tokenizer-json`` with the pinned BGE-M3 tokenizer to measure real
token counts; without it the report is clearly marked as an approximation.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml


_WORD = re.compile(r"\S+")


class TokenCounter(Protocol):
    name: str

    def spans(self, text: str) -> list[tuple[int, int]]: ...


@dataclass(frozen=True)
class WhitespaceTokenCounter:
    name: str = "whitespace-approximation"

    def spans(self, text: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in _WORD.finditer(text)]


class BgeTokenizerCounter:
    name = "BGE-M3 tokenizer.json"

    def __init__(self, tokenizer_json: Path) -> None:
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer_json))

    def spans(self, text: str) -> list[tuple[int, int]]:
        return [tuple(offset) for offset in self._tokenizer.encode(text).offsets if offset[0] < offset[1]]


def load_profiles(path: Path) -> dict[str, dict[str, int]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    profiles = payload["benchmark_profiles"]
    return {
        name: {field: int(values[field]) for field in ("target_tokens", "overlap_tokens")}
        for name, values in profiles.items()
    }


def chunk_text(text: str, *, target_tokens: int, overlap_tokens: int, counter: TokenCounter) -> list[str]:
    spans = counter.spans(text)
    if not spans:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(spans):
        end = min(start + target_tokens, len(spans))
        if end < len(spans):
            # Prefer a paragraph boundary without violating the token budget.
            candidate = text.rfind("\n\n", spans[start][0], spans[end - 1][1])
            if candidate > spans[start][0]:
                end = next((i for i in range(start + 1, end) if spans[i][0] > candidate), end)
        chunks.append(text[spans[start][0] : spans[end - 1][1]].strip())
        if end == len(spans):
            break
        start = max(end - overlap_tokens, start + 1)
    return chunks


def nearest_rank(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[(percentile * len(ordered) + 99) // 100 - 1]


def benchmark(corpus: Path, profiles: dict[str, dict[str, int]], counter: TokenCounter) -> dict[str, object]:
    documents = [path.read_text(encoding="utf-8") for path in sorted(corpus.glob("*.md"))]
    results: dict[str, object] = {}
    for name, profile in profiles.items():
        chunks = [chunk for document in documents for chunk in chunk_text(document, counter=counter, **profile)]
        counts = [len(counter.spans(chunk)) for chunk in chunks]
        total = sum(counts)
        # Each overlapping token is embedded/indexed again in the next window.
        source_tokens = sum(len(counter.spans(document)) for document in documents)
        results[name] = {
            "target_tokens": profile["target_tokens"],
            "overlap_tokens": profile["overlap_tokens"],
            "chunks_total": len(chunks),
            "tokens_total": total,
            "duplicate_token_ratio": round((total - source_tokens) / source_tokens, 4) if source_tokens else 0.0,
            "token_count_p50": nearest_rank(counts, 50),
            "token_count_p95": nearest_rank(counts, 95),
            "maximum_tokens": max(counts, default=0),
        }
    chunk_totals = {value["chunks_total"] for value in results.values()}
    return {
        "tokenizer": counter.name,
        "documents": len(documents),
        "profiles": results,
        "warning": (
            "All candidate profiles produced the same chunk count; use a longer corpus "
            "before selecting a profile."
            if len(chunk_totals) == 1
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline eval-corpus chunk budget benchmark")
    parser.add_argument("--corpus", type=Path, default=Path("data/eval/corpus"))
    parser.add_argument("--profile", type=Path, default=Path("config/foundation/embedding_profile.yaml"))
    parser.add_argument("--tokenizer-json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    counter: TokenCounter = BgeTokenizerCounter(args.tokenizer_json) if args.tokenizer_json else WhitespaceTokenCounter()
    report = benchmark(args.corpus, load_profiles(args.profile), counter)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
