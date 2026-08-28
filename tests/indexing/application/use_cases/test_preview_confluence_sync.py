import json
from pathlib import Path

from knowledgenexus.indexing.application.use_cases import preview_confluence_sync as module


def _workspace(root: Path, rows: list[dict[str, str]]) -> None:
    version = "confluence-test"
    packet = root / "versions" / version
    packet.mkdir(parents=True)
    (root / "LATEST.txt").write_text(version, encoding="ascii")
    (packet / "documents.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_preview_compares_inventory_without_indexing(tmp_path, monkeypatch):
    previous = tmp_path / "previous"
    _workspace(previous, [
        {"page_id": "1", "source_version": "v1"},
        {"page_id": "2", "source_version": "v1"},
    ])
    selection = {
        "items": [
            {"page_id": "1", "expected_source_version": "v2"},
            {"page_id": "3", "expected_source_version": "v1"},
        ],
        "selection_identity": "identity",
    }

    def fake_main(argv):
        state = Path(argv[argv.index("--state-dir") + 1])
        run = state / "runs" / "run-1"
        run.mkdir(parents=True, exist_ok=True)
        (run / "inventory-selection.json").write_text(json.dumps(selection), encoding="utf-8")
        print(json.dumps({"status": "complete", "run_id": "run-1", "selected_pages": 2}))
        return 0

    monkeypatch.setattr(module.confluence_subtree_corpus, "main", fake_main)
    result = module.preview_sync(
        url="https://wiki.example.test/spaces/SVMC/pages/10",
        workspace=tmp_path / "current",
        snapshot_root=tmp_path,
        max_pages=100,
        reliability_profile=tmp_path / "profile.yaml",
        tokenizer_assets_dir=None,
        previous_workspace=previous,
        confluence_pat="secret",
    )
    assert result["new_pages"] == 1
    assert result["changed_pages"] == 1
    assert result["deleted_pages"] == 1
    assert result["unchanged_pages"] == 0
    assert "diagnostic_stderr" not in result


def _fake_inventory(selection: dict, run_id: str = "run-1"):
    def fake_main(argv):
        state = Path(argv[argv.index("--state-dir") + 1])
        run = state / "runs" / run_id
        run.mkdir(parents=True, exist_ok=True)
        (run / "inventory-selection.json").write_text(json.dumps(selection), encoding="utf-8")
        print(json.dumps({
            "status": "complete", "run_id": run_id,
            "selected_pages": len(selection["items"]),
        }))
        return 0
    return fake_main


def _context(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "text-snapshot-context.json").write_text(
        json.dumps({
            "base_url": "https://wiki.example.test", "space_key": "SVMC",
            "root_page_id": "10", "max_pages": 200,
            "format_version": "x", "inventory_started": True, "run_id": "r",
        }),
        encoding="utf-8",
    )


def _preview(tmp_path: Path, snapshot_root: Path, **kwargs):
    return module.preview_sync(
        url="https://wiki.example.test/spaces/SVMC/pages/10",
        workspace=tmp_path / "current",
        snapshot_root=snapshot_root,
        max_pages=100,
        reliability_profile=tmp_path / "profile.yaml",
        tokenizer_assets_dir=None,
        confluence_pat="secret",
        **kwargs,
    )


def test_preview_discovers_the_baseline_from_the_snapshot_root(tmp_path, monkeypatch):
    snapshot_root = tmp_path / "snapshots"
    baseline = snapshot_root / "job-old"
    _context(baseline)
    _workspace(baseline, [
        {"document_id": "confluence:page:1", "page_id": "1", "source_version": "v1"},
        {"document_id": "confluence:page:2", "page_id": "2", "source_version": "v1"},
    ])
    monkeypatch.setattr(module.confluence_subtree_corpus, "main", _fake_inventory({
        "items": [
            {"page_id": "1", "expected_source_version": "v1"},
            {"page_id": "3", "expected_source_version": "v1"},
        ],
        "selection_identity": "identity",
    }))

    result = _preview(tmp_path, snapshot_root)

    assert result["status"] == "complete"
    assert result["baseline_workspace"] == str(baseline)
    assert (result["new_pages"], result["changed_pages"], result["deleted_pages"]) == (1, 0, 1)
    assert result["unchanged_pages"] == 1
    assert result["canonical_url"] == "https://wiki.example.test/spaces/SVMC/pages/10"


def test_preview_reports_baseline_required_when_nothing_was_ever_published(tmp_path, monkeypatch):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    monkeypatch.setattr(module.confluence_subtree_corpus, "main", _fake_inventory({
        "items": [{"page_id": "1", "expected_source_version": "v1"}],
        "selection_identity": "identity",
    }))

    result = _preview(tmp_path, snapshot_root)

    assert result["status"] == "baseline_required"
    assert result["baseline_found"] is False
    assert result["new_pages"] == 1
    assert result["deleted_pages"] == 0
