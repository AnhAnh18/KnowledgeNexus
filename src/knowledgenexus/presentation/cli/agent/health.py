"""health — API health check."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from knowledgenexus.presentation.cli.agent.formatters import format_health_text
from knowledgenexus.presentation.cli.agent.http import make_request


def run() -> None:
    health = make_request("GET", "/api/v1/health")
    print(format_health_text(health))


def build_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("health", help="Health check")
    parser.set_defaults(func=_dispatch)


def _dispatch(_args: argparse.Namespace) -> None:
    run()


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(description="Health check").parse_args(argv)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
