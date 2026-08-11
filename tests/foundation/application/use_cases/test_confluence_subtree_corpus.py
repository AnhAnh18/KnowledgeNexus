from pathlib import Path

import pytest

from knowledgenexus.foundation.application.use_cases.confluence_subtree_corpus import (
    AttachmentMetadata,
    ConfluenceSubtreeCorpusConfig,
    ConfluenceSubtreeCorpusHarness,
    DrawioReference,
    match_drawio_attachment,
    partition_page_ids,
)


def test_partition_250_pages_is_100_100_50():
    assert [len(x) for x in partition_page_ids([str(i) for i in range(250)])] == [100, 100, 50]


def test_bounds_reject_more_than_5000():
    with pytest.raises(ValueError):
        ConfluenceSubtreeCorpusConfig(max_pages=5001)


def test_drawio_exact_parent_name_and_positive_version():
    ref = DrawioReference("p1", "architecture.drawio", "4")
    assert match_drawio_attachment(ref, [AttachmentMetadata("a", "p1", "architecture.drawio", "4")]).attachment_id == "a"
    assert match_drawio_attachment(ref, [AttachmentMetadata("a", "p2", "architecture.drawio", "4")]) is None


def test_drawio_ambiguity_fails_closed():
    ref = DrawioReference("p1", "a.xml", "1")
    rows = [AttachmentMetadata("a", "p1", "a.xml", "1"), AttachmentMetadata("b", "p1", "a.xml", "1")]
    with pytest.raises(ValueError):
        match_drawio_attachment(ref, rows)


def test_capture_pages_publishes_each_page_and_resumes(tmp_path: Path):
    calls = []
    def fetch(page_id: str) -> bytes:
        calls.append(page_id)
        return page_id.encode()
    harness = ConfluenceSubtreeCorpusHarness(config=ConfluenceSubtreeCorpusConfig(max_pages=250, page_bytes=10), state_dir=tmp_path / "state")
    first = harness.capture_pages(["1", "2", "3"], fetch)
    second = harness.capture_pages(["1", "2", "3"], fetch)
    assert first["captured_pages"] == 3
    assert second["captured_pages"] == 0
    assert calls == ["1", "2", "3"]
