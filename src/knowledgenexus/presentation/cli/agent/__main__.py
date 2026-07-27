from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from knowledgenexus.presentation.cli.agent import (
    health,
    list_docs,
    search,
    stats,
)
from knowledgenexus.presentation.cli.agent.http import CliError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kn",
        description="KnowledgeNexus agent CLI — Skill/Cline entrypoint for read APIs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run kn search "table layout"
  uv run kn search "MCP protocol" --top-k 10
  uv run kn list-docs --limit 20
  uv run kn stats
  uv run kn health
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    search.build_parser(subparsers)
    list_docs.build_parser(subparsers)
    stats.build_parser(subparsers)
    health.build_parser(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.command:
        parser.print_help()
        return 1
    try:
        args.func(args)
    except CliError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
