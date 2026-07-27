"""list-docs — list indexed documents via API."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from knowledgenexus.presentation.cli.agent.formatters import format_documents_text
from knowledgenexus.presentation.cli.agent.http import make_request


def run(limit: int = 100, offset: int = 0) -> None:
    result = make_request(
        "GET",
        "/api/v1/documents",
        params={"limit": limit, "offset": offset},
    )
    print(format_documents_text(result))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("list-docs", help="List documents")
    parser.add_argument("--limit", type=int, default=100, help="Max documents (default: 100)")
    parser.add_argument("--offset", type=int, default=0, help="Skip documents (default: 0)")
    parser.set_defaults(func=_dispatch)


def _dispatch(args: argparse.Namespace) -> None:
    run(limit=args.limit, offset=args.offset)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List documents")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    run(limit=args.limit, offset=args.offset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
