from __future__ import annotations

import pytest

from knowledgenexus.foundation.application.use_cases.process_confluence_media_attachment import (
    ProcessConfluenceMediaAttachment,
)
from knowledgenexus.foundation.domain.models.confluence_page_observation import RawHttpObservation
from knowledgenexus.foundation.domain.models.media_body_materialization import MediaAttachmentBodyEnvelope
from knowledgenexus.foundation.domain.models.media_materialization import ConfluenceAttachmentObservation
from knowledgenexus.foundation.domain.models.media_processing import (
    ImageOcrResponse,
    MediaProcessingError,
    MediaProcessingFailureCategory,
    OcrLabelResult,
    PdfPageTextResult,
    PdfTextExtractionResponse,
)
from knowledgenexus.foundation.infrastructure.processors.media_attachment_processors import (
    DrawioProcessor,
    ImageOcrProcessor,
    PdfTextProcessor,
)


def _envelope(body: bytes = b"body", *, filename: str = "file.pdf") -> MediaAttachmentBodyEnvelope:
    return MediaAttachmentBodyEnvelope(
        format_version="1",
        evidence_kind="confluence_attachment_body",
        attachment_id="2000",
        parent_page_id="1000",
        filename=filename,
        source_version="1",
        http_status=200,
        body_encoding="base64",
        body_bytes=body,
    )


def _observation(*, filename: str = "file.pdf", mime_type: str | None = "application/pdf", size: int = 4) -> ConfluenceAttachmentObservation:
    return ConfluenceAttachmentObservation(
        attachment_id="2000",
        parent_page_id="1000",
        filename=filename,
        mime_type=mime_type,
        size_bytes=size,
        source_version="1",
        updated_at=None,
        crawled_at="2026-08-05T00:00:00Z",
    )


class _PdfCapability:
    def extract_pdf_text(self, *, body: bytes) -> PdfTextExtractionResponse:
        return PdfTextExtractionResponse(
            capability_id="pdf-text-fixture-v1",
            capability_version="1",
            pages=(PdfPageTextResult(page_number=1, text="hello"),),
        )


class _OcrCapability:
    def extract_labels(self, *, body: bytes) -> ImageOcrResponse:
        return ImageOcrResponse(
            capability_id="image-ocr-fixture-v1",
            capability_version="1",
            labels=(OcrLabelResult(image_index=1, text="label", confidence=0.75),),
        )


def test_dispatches_pdf_and_image_by_exact_policy() -> None:
    use_case = ProcessConfluenceMediaAttachment(
        pdf_processor=PdfTextProcessor(capability=_PdfCapability()),
        ocr_processor=ImageOcrProcessor(capability=_OcrCapability()),
    )
    pdf = use_case.execute(envelope=_envelope(), observation=_observation())
    assert pdf.asset["processing_status"] == "parsed"
    image = use_case.execute(
        envelope=_envelope(filename="chart.png"),
        observation=_observation(filename="chart.png", mime_type="image/png"),
    )
    assert image.asset["processing_status"] == "ocr"


def test_drawio_route_is_offline_and_deterministic() -> None:
    body = (
        b'<mxfile><diagram id="page"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0"/>'
        b'<mxCell id="2" parent="1" vertex="1" value="A"><mxGeometry/></mxCell>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )
    use_case = ProcessConfluenceMediaAttachment(drawio_processor=DrawioProcessor())
    first = use_case.execute(
        envelope=_envelope(body, filename="diagram.drawio"),
        observation=_observation(
            filename="diagram.drawio",
            mime_type="application/vnd.jgraph.mxfile",
            size=len(body),
        ),
    )
    second = use_case.execute(
        envelope=_envelope(body, filename="diagram.drawio"),
        observation=_observation(
            filename="diagram.drawio",
            mime_type="application/vnd.jgraph.mxfile",
            size=len(body),
        ),
    )
    assert first == second
    assert first.asset["processing_status"] == "parsed"


def test_missing_capability_returns_failed_asset_without_derived_fields() -> None:
    result = ProcessConfluenceMediaAttachment().execute(
        envelope=_envelope(), observation=_observation()
    )
    assert result.asset["processing_status"] == "failed"
    assert result.failure_category is MediaProcessingFailureCategory.CAPABILITY_UNAVAILABLE
    assert result.asset["extracted_text"] is None


def test_unsupported_and_mismatched_inputs_fail_before_processing() -> None:
    use_case = ProcessConfluenceMediaAttachment(drawio_processor=DrawioProcessor())
    with pytest.raises(MediaProcessingError) as unsupported:
        use_case.execute(
            envelope=_envelope(filename="data.zip"),
            observation=_observation(filename="data.zip", mime_type="application/zip"),
        )
    assert unsupported.value.category is MediaProcessingFailureCategory.UNSUPPORTED_MEDIA
    with pytest.raises(MediaProcessingError) as mismatch:
        use_case.execute(
            envelope=_envelope(),
            observation=_observation(size=3),
        )
    assert mismatch.value.category is MediaProcessingFailureCategory.INVALID_INPUT
    with pytest.raises(MediaProcessingError) as wrong_type:
        use_case.execute(envelope=object(), observation=object())
    assert wrong_type.value.category is MediaProcessingFailureCategory.INVALID_INPUT


def test_forged_processor_result_is_sanitized() -> None:
    class _Forged:
        def process(self, *, envelope: object, observation: object) -> object:
            return object()

    use_case = ProcessConfluenceMediaAttachment(pdf_processor=_Forged())
    with pytest.raises(MediaProcessingError) as error:
        use_case.execute(envelope=_envelope(), observation=_observation())
    assert error.value.category is MediaProcessingFailureCategory.MALFORMED_RESULT


def test_dispatch_rejects_a_result_with_the_wrong_processor_detail() -> None:
    xml_body = (
        b'<mxfile><diagram id="page"><mxGraphModel><root>'
        b'<mxCell id="0"/><mxCell id="1" parent="0" vertex="1" value="A"><mxGeometry/></mxCell>'
        b'</root></mxGraphModel></diagram></mxfile>'
    )

    class _WrongProcessor:
        def process(self, *, envelope: object, observation: object) -> object:
            return DrawioProcessor().process(envelope=envelope, observation=observation)

    use_case = ProcessConfluenceMediaAttachment(pdf_processor=_WrongProcessor())
    with pytest.raises(MediaProcessingError) as error:
        use_case.execute(
            envelope=_envelope(xml_body),
            observation=_observation(size=len(xml_body)),
        )
    assert error.value.category is MediaProcessingFailureCategory.MALFORMED_RESULT
