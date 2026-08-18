"""stats — store statistics via API."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from knowledgenexus.presentation.cli.agent.formatters import format_stats_text
from knowledgenexus.presentation.cli.agent.http import make_request


def run() -> None:
    stats = make_request("GET", "/api/v1/store/stats")
    print(format_stats_text(stats))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("stats", help="Get store statistics")
    parser.set_defaults(func=_dispatch)


def _dispatch(_args: argparse.Namespace) -> None:
    run()


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(description="Get store statistics").parse_args(argv)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
