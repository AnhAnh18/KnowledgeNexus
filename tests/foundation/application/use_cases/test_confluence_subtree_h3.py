from types import SimpleNamespace

from knowledgenexus.foundation.application.use_cases.confluence_subtree_corpus import (
    AttachmentMetadata,
    DrawioReference,
    capture_drawio_assets,
    capture_drawio_with_production_components,
    process_preserved_pages,
)
from knowledgenexus.foundation.domain.models.media_materialization import ConfluenceAttachmentObservation
from knowledgenexus.foundation.domain.models.media_body_materialization import MediaAttachmentBodyEnvelope, MediaAttachmentRawArtifact, MediaAttachmentPublicationOutcome
from knowledgenexus.foundation.domain.models.media_materialization import MediaPolicyDecision


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


def test_production_drawio_composition_matches_and_acknowledges_after_processing():
    ref = DrawioReference("1", "diagram.drawio", "3")
    obs = ConfluenceAttachmentObservation("att12", "1", "diagram.drawio", "application/xml", 5, "3", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z")
    envelope = MediaAttachmentBodyEnvelope("1", "confluence_attachment_body", "att12", "1", "diagram.drawio", "3", 200, "base64", b"<xml/>")
    artifact = MediaAttachmentRawArtifact(path=__import__('pathlib').Path.cwd() / "x", attachment_id="att12", body_sha256="a" * 64, byte_count=5, raw_uri="raw://confluence/attachments/att12/" + "a" * 64, outcome=MediaAttachmentPublicationOutcome.PUBLISHED)
    class Observer:
        def list_attachments(self, page_id):
            return (obs, ConfluenceAttachmentObservation("att13", "1", "other.pdf", "application/pdf", 2, "3", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"))
    class Materializer:
        def __init__(self):
            self.raw_attachment_store = self
        def execute(self, *, observation, decision):
            assert isinstance(decision, MediaPolicyDecision)
            return type("R", (), {"artifact": artifact})()
        def read_attachment(self, *, attachment_id, content_hash):
            return envelope
    class Processor:
        def execute(self, *, envelope, observation):
            return type("R", (), {"asset": {"media_id": "m"}})()
    acknowledged = []
    result = capture_drawio_with_production_components(references=(ref,), attachment_observer=Observer(), body_materializer=Materializer(), media_processor=Processor(), acknowledge=acknowledged.append)
    assert result["drawio_references_resolved"] == 1
    assert acknowledged == ["att12"]
