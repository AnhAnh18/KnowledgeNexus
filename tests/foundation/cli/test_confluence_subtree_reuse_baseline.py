import argparse
import json
import uuid
from pathlib import Path

from knowledgenexus.foundation.cli import confluence_subtree_corpus as mod
from knowledgenexus.foundation.domain.models.confluence_crawl_run import CrawlRunId
from knowledgenexus.foundation.domain.models.confluence_page_set import ConfluencePageWorkItem
from knowledgenexus.foundation.domain.models.confluence_raw_page_artifact import (
    ConfluenceRawPageEnvelope,
)
from knowledgenexus.foundation.infrastructure.raw_store import (
    ConfluenceRawPageGenerationStore,
)


def _item(page_id: str, version: str) -> ConfluencePageWorkItem:
    return ConfluencePageWorkItem(
        page_id=page_id, crawled_at="2026-08-28T00:00:00Z",
        expected_source_version=version,
    )


def _publish_baseline_page(raw_root: Path, run_id: CrawlRunId, page_id: str, version: str) -> bytes:
    body = json.dumps({"id": page_id, "version": {"number": int(version)}}).encode("utf-8")
    store = ConfluenceRawPageGenerationStore(raw_root=raw_root)
    store.publish_page(envelope=ConfluenceRawPageEnvelope.capture(
        run_id=run_id, page_id=page_id, source_version=version,
        http_status=200, body_bytes=body,
    ))
    return body


def _args(**kw) -> argparse.Namespace:
    base = dict(
        reuse_baseline_raw_root=None, reuse_baseline_run_id=None, reuse_unchanged_path=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_no_reuse_inputs_returns_empty(tmp_path):
    assert mod._load_reuse_baseline_bodies(_args(), (_item("1", "1"),)) == {}


def test_unchanged_page_body_is_loaded_and_changed_page_is_skipped(tmp_path):
    raw_root = tmp_path / "baseline" / ".raw"
    raw_root.mkdir(parents=True)
    run_id = CrawlRunId(str(uuid.uuid4()))
    body1 = _publish_baseline_page(raw_root, run_id, "1", "5")
    _publish_baseline_page(raw_root, run_id, "2", "3")  # baseline v3, but selection is v4 → changed

    unchanged_path = tmp_path / "reuse.json"
    unchanged_path.write_text(json.dumps([
        {"page_id": "1", "source_version": "5"},
        {"page_id": "2", "source_version": "3"},
    ]), encoding="utf-8")

    args = _args(
        reuse_baseline_raw_root=str(raw_root),
        reuse_baseline_run_id=str(run_id),
        reuse_unchanged_path=str(unchanged_path),
    )
    # Selection: page 1 unchanged (v5==v5), page 2 changed (v4 != baseline v3).
    bodies = mod._load_reuse_baseline_bodies(args, (_item("1", "5"), _item("2", "4")))

    assert bodies == {"1": body1}


def test_missing_baseline_raw_page_is_skipped(tmp_path):
    raw_root = tmp_path / "baseline" / ".raw"
    raw_root.mkdir(parents=True)
    run_id = CrawlRunId(str(uuid.uuid4()))
    # Nothing published for page "1".
    unchanged_path = tmp_path / "reuse.json"
    unchanged_path.write_text(json.dumps([{"page_id": "1", "source_version": "5"}]), encoding="utf-8")

    args = _args(
        reuse_baseline_raw_root=str(raw_root),
        reuse_baseline_run_id=str(run_id),
        reuse_unchanged_path=str(unchanged_path),
    )
    assert mod._load_reuse_baseline_bodies(args, (_item("1", "5"),)) == {}
