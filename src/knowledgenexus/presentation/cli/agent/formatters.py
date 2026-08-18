"""Stdout / Markdown formatters for agent CLI results."""

from __future__ import annotations

from typing import Any


def format_search_text(query: str, result: dict[str, Any]) -> str:
    total = result.get("total", 0)
    results = result.get("results", [])
    lines = [f'Found {total} result(s) for "{query}".', ""]

    for idx, chunk in enumerate(results):
        citation = chunk.get("citation", {})
        score = chunk.get("score", 0.0)
        content = chunk.get("content", "")

        lines.append(f"--- Result {idx + 1} (score: {score:.4f}) ---")
        lines.append(f"Title: {citation.get('title', 'N/A')}")
        lines.append(
            f"Source: {citation.get('source_type', 'N/A')} / "
            f"{citation.get('source_id', 'N/A')}"
        )

        file_path = citation.get("file_path")
        if file_path:
            line_info = ""
            if citation.get("line_start") is not None:
                line_info = (
                    f":{citation['line_start']}-{citation.get('line_end', citation['line_start'])}"
                )
            lines.append(f"File: {file_path}{line_info}")

        if citation.get("url"):
            lines.append(f"URL: {citation['url']}")
        if citation.get("heading_path"):
            lines.append(f"Heading: {citation['heading_path']}")

        lines.append(f"\nContent:\n{content}\n")

    return "\n".join(lines)


def format_stats_text(result: dict[str, Any]) -> str:
    """Format store statistics into a readable summary."""
    lines = ["Store Statistics", ""]

    # Common stat fields — gracefully handle missing keys
    for key in ("total_documents", "total_chunks", "total_vectors", "collection_name"):
        if key in result:
            label = key.replace("_", " ").title()
            lines.append(f"  {label}: {result[key]}")

    # Include any remaining fields not explicitly listed above
    known_keys = {"total_documents", "total_chunks", "total_vectors", "collection_name"}
    for key, value in result.items():
        if key not in known_keys:
            label = key.replace("_", " ").title()
            lines.append(f"  {label}: {value}")

    return "\n".join(lines)


def format_health_text(result: dict[str, Any]) -> str:
    """Format health check response into a readable summary."""
    status = result.get("status", "unknown")
    lines = [f"API Status: {status}", ""]

    for key, value in result.items():
        if key == "status":
            continue
        label = key.replace("_", " ").title()
        lines.append(f"  {label}: {value}")

    return "\n".join(lines)


def format_documents_text(result: dict[str, Any]) -> str:
    total = result.get("total", 0)
    docs = result.get("documents", [])
    lines = [
        f"Documents: {total} total "
        f"(showing {len(docs)}, offset {result.get('offset', 0)})",
        "",
    ]

    for idx, doc in enumerate(docs):
        lines.append(f"{idx + 1}. {doc.get('title', 'N/A')}")
        lines.append(f"   ID: {doc.get('id', 'N/A')}")
        lines.append(
            f"   Source: {doc.get('source_type', 'N/A')} / {doc.get('source_id', 'N/A')}"
        )
        if doc.get("url"):
            lines.append(f"   URL: {doc['url']}")
        lines.append(f"   Created: {doc.get('created_at', 'N/A')}")
        lines.append("")

    return "\n".join(lines)
