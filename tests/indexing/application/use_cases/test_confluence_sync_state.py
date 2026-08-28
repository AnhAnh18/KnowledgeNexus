import json
from pathlib import Path

from knowledgenexus.indexing.application.use_cases.confluence_sync_state import (
    PageState,
    RootIdentity,
    build_sync_plan,
    find_baseline_workspace,
    published_packet_dir,
    read_packet_pages,
    read_root_identity,
)

_IDENTITY = RootIdentity("https://wiki.example.test", "SVMC", "10")


def _publish(workspace: Path, rows: list[dict[str, str]], *, version: str = "confluence-a") -> None:
    packet = workspace / "versions" / version
    packet.mkdir(parents=True)
    (packet / "documents.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (workspace / "LATEST.txt").write_text(version + "\n", encoding="ascii")


def _context(workspace: Path, identity: RootIdentity = _IDENTITY) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "text-snapshot-context.json").write_text(
        json.dumps({
            "base_url": identity.base_url, "space_key": identity.space_key,
            "root_page_id": identity.root_page_id, "max_pages": 200,
            "format_version": "x", "inventory_started": True, "run_id": "r",
        }),
        encoding="utf-8",
    )


def _page(page_id: str, version: str) -> PageState:
    return PageState(f"confluence:page:{page_id}", page_id, version)


def test_plan_splits_pages_into_new_changed_deleted_and_unchanged():
    plan = build_sync_plan(
        baseline={"1": _page("1", "v1"), "2": _page("2", "v1"), "3": _page("3", "v1")},
        current={"1": _page("1", "v2"), "2": _page("2", "v1"), "4": _page("4", "v1")},
    )
    assert plan.new_page_ids == ("4",)
    assert plan.changed_page_ids == ("1",)
    assert plan.deleted_page_ids == ("3",)
    assert plan.unchanged_page_ids == ("2",)
    assert plan.touched_page_ids == ("1", "4")
    assert plan.counts() == {
        "new_pages": 1, "changed_pages": 1, "deleted_pages": 1, "unchanged_pages": 1,
    }


def test_packet_pages_are_read_from_the_published_version(tmp_path):
    _publish(tmp_path, [
        {"document_id": "confluence:page:1", "page_id": "1", "source_version": "v1"},
        {"document_id": "confluence:page:2", "page_id": "2", "source_version": "v7"},
    ])
    pages = read_packet_pages(tmp_path)
    assert pages["2"] == PageState("confluence:page:2", "2", "v7")
    assert published_packet_dir(tmp_path) == tmp_path / "versions" / "confluence-a"


def test_unpublished_workspace_has_no_baseline(tmp_path):
    (tmp_path / "versions").mkdir()
    assert published_packet_dir(tmp_path) is None
    assert read_packet_pages(tmp_path) == {}


def test_workspace_claiming_a_traversal_version_is_rejected(tmp_path):
    (tmp_path / "LATEST.txt").write_text("confluence-../escape\n", encoding="ascii")
    assert published_packet_dir(tmp_path) is None


def test_baseline_is_the_newest_published_workspace_for_the_same_root(tmp_path):
    older, newer, other, unpublished = (
        tmp_path / "older", tmp_path / "newer", tmp_path / "other", tmp_path / "unpublished"
    )
    for workspace in (older, newer, unpublished):
        _context(workspace)
    _context(other, RootIdentity("https://wiki.example.test", "SVMC", "999"))
    rows = [{"document_id": "confluence:page:1", "page_id": "1", "source_version": "v1"}]
    _publish(older, rows)
    _publish(newer, rows, version="confluence-b")
    _publish(other, rows)
    import os
    os.utime(older / "LATEST.txt", (1_600_000_000, 1_600_000_000))
    os.utime(newer / "LATEST.txt", (1_700_000_000, 1_700_000_000))

    assert find_baseline_workspace(snapshot_root=tmp_path, identity=_IDENTITY) == newer
    assert find_baseline_workspace(
        snapshot_root=tmp_path, identity=_IDENTITY, exclude=frozenset({"newer"})
    ) == older


def test_root_identity_requires_a_context_file(tmp_path):
    assert read_root_identity(tmp_path) is None
    _context(tmp_path)
    assert read_root_identity(tmp_path) == _IDENTITY
    assert _IDENTITY.canonical_url == "https://wiki.example.test/spaces/SVMC/pages/10"
