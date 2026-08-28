"""Shared sync state for Confluence subtree re-ingestion.

A "sync" answers one question about an already indexed root: relative to the
last packet we published for it, which pages are new, which changed, which
disappeared, and which are untouched.  Everything here reads only what is
already on disk -- Foundation workspaces under the snapshot root -- so the
same helpers serve the read-only preview and the mutating apply run without
either of them owning a private notion of "last accepted state".

Identity of a root is the Foundation context file's
``(base_url, space_key, root_page_id)`` triple, never a submitted URL string:
the same page is reachable through short links, ``viewpage.action`` and the
canonical ``/spaces/.../pages/<id>`` form, and matching on the raw text would
silently treat those as different roots.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_CONTEXT_FILE = "text-snapshot-context.json"
_LATEST_FILE = "LATEST.txt"
_DOCUMENTS_FILE = "documents.jsonl"

# Confluence document ids in a Foundation packet, e.g. "confluence:page:12345".
_DOCUMENT_ID_PREFIX = "confluence:page:"


@dataclass(frozen=True)
class RootIdentity:
    """The durable identity of an ingested subtree root."""

    base_url: str
    space_key: str
    root_page_id: str

    @property
    def canonical_url(self) -> str:
        return f"{self.base_url}/spaces/{self.space_key}/pages/{self.root_page_id}"


@dataclass(frozen=True)
class PageState:
    """One page as a published packet recorded it."""

    document_id: str
    page_id: str
    source_version: str


@dataclass(frozen=True)
class SyncPlan:
    """What an apply run would have to do, expressed in page ids."""

    new_page_ids: tuple[str, ...]
    changed_page_ids: tuple[str, ...]
    deleted_page_ids: tuple[str, ...]
    unchanged_page_ids: tuple[str, ...]

    @property
    def touched_page_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.new_page_ids) | set(self.changed_page_ids)))

    def counts(self) -> dict[str, int]:
        return {
            "new_pages": len(self.new_page_ids),
            "changed_pages": len(self.changed_page_ids),
            "deleted_pages": len(self.deleted_page_ids),
            "unchanged_pages": len(self.unchanged_page_ids),
        }


def read_root_identity(workspace: Path) -> RootIdentity | None:
    """Read the root a workspace was created for, or None if it has none."""
    context = workspace / _CONTEXT_FILE
    if not context.is_file():
        return None
    try:
        payload = json.loads(context.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(payload) is not dict:
        return None
    values = [payload.get(key) for key in ("base_url", "space_key", "root_page_id")]
    if any(type(value) is not str or not value for value in values):
        return None
    return RootIdentity(*values)  # type: ignore[arg-type]


def published_packet_dir(workspace: Path) -> Path | None:
    """Resolve the packet a workspace published, or None if it never did."""
    latest = workspace / _LATEST_FILE
    if not latest.is_file():
        return None
    try:
        version = latest.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    # A published version name is a single path component by construction; a
    # workspace that says otherwise is corrupt, not a baseline.
    if not version.startswith("confluence-") or Path(version).name != version:
        return None
    packet = workspace / "versions" / version
    return packet if (packet / _DOCUMENTS_FILE).is_file() else None


def read_packet_pages(workspace: Path) -> dict[str, PageState]:
    """Map ``page_id -> PageState`` for the packet a workspace published.

    Returns an empty mapping when the workspace has no published packet, which
    is what makes "no baseline yet" a first-class, non-exceptional answer.
    """
    packet = published_packet_dir(workspace)
    if packet is None:
        return {}
    pages: dict[str, PageState] = {}
    try:
        text = (packet / _DOCUMENTS_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return {}
        if type(row) is not dict:
            return {}
        document_id = row.get("document_id")
        page_id = row.get("page_id")
        version = row.get("source_version")
        if type(page_id) is not str and type(document_id) is str:
            page_id = document_id.removeprefix(_DOCUMENT_ID_PREFIX)
        if type(document_id) is not str and type(page_id) is str:
            document_id = _DOCUMENT_ID_PREFIX + page_id
        if (
            type(document_id) is not str
            or type(page_id) is not str or not page_id
            or type(version) is not str or not version
        ):
            continue
        pages[page_id] = PageState(document_id, page_id, version)
    return pages


def find_baseline_workspace(
    *, snapshot_root: Path, identity: RootIdentity, exclude: frozenset[str] = frozenset()
) -> Path | None:
    """Find the most recently published workspace for this exact root.

    The snapshot root is scanned instead of the job table on purpose: the
    baseline is a fact about what was published on disk, so it survives a job
    database that was reset, pruned, or written by an earlier build.
    """
    if not snapshot_root.is_dir():
        return None
    best: tuple[float, Path] | None = None
    for candidate in snapshot_root.iterdir():
        if not candidate.is_dir() or candidate.name in exclude:
            continue
        if read_root_identity(candidate) != identity:
            continue
        packet = published_packet_dir(candidate)
        if packet is None:
            continue
        try:
            published_at = (candidate / _LATEST_FILE).stat().st_mtime
        except OSError:
            continue
        if best is None or published_at > best[0]:
            best = (published_at, candidate)
    return None if best is None else best[1]


def build_sync_plan(
    *, baseline: dict[str, PageState], current: dict[str, PageState]
) -> SyncPlan:
    """Diff two packet page maps.

    A page counts as *changed* when Confluence reports a different
    ``source_version``; that is the same signal the inventory phase records,
    so preview and apply cannot disagree about what changed.
    """
    new = sorted(set(current) - set(baseline))
    deleted = sorted(set(baseline) - set(current))
    both = set(current) & set(baseline)
    changed = sorted(
        page_id for page_id in both
        if current[page_id].source_version != baseline[page_id].source_version
    )
    unchanged = sorted(both - set(changed))
    return SyncPlan(tuple(new), tuple(changed), tuple(deleted), tuple(unchanged))
