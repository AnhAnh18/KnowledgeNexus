"""search — retrieve knowledge chunks via API."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from knowledgenexus.presentation.cli.agent.formatters import format_search_text
from knowledgenexus.presentation.cli.agent.http import make_request


def run(query: str, top_k: int = 5, score_threshold: float = 0.0) -> None:
    result = make_request(
        "POST",
        "/api/v1/retrieve",
        data={
            "query": query,
            "top_k": top_k,
            "score_threshold": score_threshold,
            "filters": {},
        },
    )
    print(format_search_text(query, result))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("search", help="Search knowledge chunks")
    parser.add_argument("query", type=str, help="Search query text")
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        choices=range(1, 51),
        help="Number of results (default: 5, max: 50)",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.0,
        help="Min score (default: 0.0)",
    )
    parser.set_defaults(func=_dispatch)


def _dispatch(args: argparse.Namespace) -> None:
    run(args.query, top_k=args.top_k, score_threshold=args.score_threshold)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search knowledge chunks")
    parser.add_argument("query", type=str, help="Search query text")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--score-threshold", type=float, default=0.0)
    args = parser.parse_args(argv)
    run(args.query, top_k=args.top_k, score_threshold=args.score_threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
