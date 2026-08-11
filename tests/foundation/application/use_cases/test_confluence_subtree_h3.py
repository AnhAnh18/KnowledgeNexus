from types import SimpleNamespace

from knowledgenexus.foundation.application.use_cases.confluence_subtree_corpus import (
    AttachmentMetadata,
    DrawioReference,
    capture_drawio_assets,
    process_preserved_pages,
)


class _Processor:
    def execute(self, *, request):
        return SimpleNamespace(
            documents=({"document_id": "d1"},),
            chunks=({"chunk_id": "c1"},),
            metrics={"succeeded_pages": 1},
            reference_intents_by_page=(),
        )


def test_process_preserved_pages_is_injected_and_non_empty():
    result = process_preserved_pages(processor=_Processor(), request=object())
    assert result["documents"] == ({"document_id": "d1"},)
    assert result["chunks"] == ({"chunk_id": "c1"},)


def test_capture_drawio_fetches_only_exact_match():
    fetched = []
    ref = DrawioReference("1", "diagram.drawio", "3")

    def list_attachments(page_id):
        return (
            AttachmentMetadata("11", page_id, "other.pdf", "3", "application/pdf"),
            AttachmentMetadata("12", page_id, "diagram.drawio", "3"),
        )

    def fetch_body(metadata):
        fetched.append(metadata.attachment_id)
        return b"<xml/>"

    result = capture_drawio_assets(
        references=(ref,),
        list_attachments=list_attachments,
        fetch_body=fetch_body,
        process_body=lambda metadata, body: {"media_id": metadata.attachment_id},
    )
    assert fetched == ["12"]
    assert result["drawio_references_resolved"] == 1
    assert result["media_assets"] == ({"media_id": "12"},)
