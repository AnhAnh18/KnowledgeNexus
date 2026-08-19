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


def test_drawio_name_comparison_strips_whitespace():
    # Confluence can store files with leading/trailing spaces (e.g., " Relation" or "Relation ")
    ref = DrawioReference("p1", "Relation", "1")
    
    # 1. Leading space in attachment filename
    assert match_drawio_attachment(ref, [AttachmentMetadata("a", "p1", " Relation", "1")]).attachment_id == "a"
    
    # 2. Trailing space in attachment filename
    assert match_drawio_attachment(ref, [AttachmentMetadata("b", "p1", "Relation ", "1")]).attachment_id == "b"

    # 3. Leading/trailing space in reference filename
    ref_with_space = DrawioReference("p1", " Relation ", "1")
    assert match_drawio_attachment(ref_with_space, [AttachmentMetadata("c", "p1", "Relation", "1")]).attachment_id == "c"


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


def test_extensionless_data_center_diagram_is_matched_but_preview_and_draft_are_not():
    """Confluence Data Center names the diagram source without an extension.

    A real page carries three files per diagram: the source with no extension,
    a ".png" render and a "~....tmp" editor draft. The old extension whitelist
    rejected the only one that matters, so every capture reported
    "incomplete" without ever downloading anything.
    """
    from knowledgenexus.foundation.application.use_cases.confluence_subtree_corpus import (
        is_drawio_attachment_name,
    )

    source = "Untitled Diagram-1786592716372"
    assert is_drawio_attachment_name(source)
    assert not is_drawio_attachment_name(source + ".png")
    assert not is_drawio_attachment_name("~" + source + ".tmp")
    # Named extensions keep working.
    assert is_drawio_attachment_name("architecture.drawio")
    assert is_drawio_attachment_name("architecture.DRAWIO.XML")
    assert is_drawio_attachment_name("architecture.xml")
    assert not is_drawio_attachment_name("payload.exe")
    assert not is_drawio_attachment_name("")
    assert not is_drawio_attachment_name(None)

    ref = DrawioReference("2894336117", source, "4")
    attachments = [
        AttachmentMetadata("a1", "2894336117", "~" + source + ".tmp", "4"),
        AttachmentMetadata("a2", "2894336117", source + ".png", "4"),
        AttachmentMetadata("a3", "2894336117", source, "4"),
    ]

    matched = match_drawio_attachment(ref, attachments)

    assert matched is not None and matched.attachment_id == "a3"
