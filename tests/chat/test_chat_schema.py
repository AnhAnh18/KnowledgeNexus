"""Tests for ChatSchema — Pydantic validation of request/response models.

Covers: min/max length, top_k bounds, score_threshold bounds, default values.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from knowledgenexus.presentation.api.v1.schemas.chat_schema import (
    ChatAnswerSchema,
    ChatRequestSchema,
    ChatResponseSchema,
)
from knowledgenexus.presentation.api.v1.schemas.retrieve_schema import CitationSchema


class TestChatRequestSchemaValidation:
    """Verify ChatRequestSchema input validation."""

    def test_valid_request(self):
        req = ChatRequestSchema(question="What is SPen SDK?")
        assert req.question == "What is SPen SDK?"
        assert req.top_k == 5  # default
        assert req.score_threshold == 0.0  # default

    def test_valid_request_with_params(self):
        req = ChatRequestSchema(question="test", top_k=20, score_threshold=0.7)
        assert req.top_k == 20
        assert req.score_threshold == 0.7

    def test_empty_question_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequestSchema(question="")

    def test_question_exceeds_max_length_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequestSchema(question="A" * 2001)

    def test_question_at_max_length_accepted(self):
        req = ChatRequestSchema(question="A" * 2000)
        assert len(req.question) == 2000

    def test_top_k_below_min_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequestSchema(question="test", top_k=0)

    def test_top_k_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequestSchema(question="test", top_k=51)

    def test_top_k_at_max_accepted(self):
        req = ChatRequestSchema(question="test", top_k=50)
        assert req.top_k == 50

    def test_score_threshold_below_min_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequestSchema(question="test", score_threshold=-0.1)

    def test_score_threshold_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequestSchema(question="test", score_threshold=1.1)

    def test_score_threshold_at_bounds_accepted(self):
        req1 = ChatRequestSchema(question="test", score_threshold=0.0)
        req2 = ChatRequestSchema(question="test", score_threshold=1.0)
        assert req1.score_threshold == 0.0
        assert req2.score_threshold == 1.0


class TestChatResponseSchema:
    """Verify ChatResponseSchema serialization."""

    def test_valid_response(self):
        resp = ChatResponseSchema(
            question="test",
            answer=ChatAnswerSchema(
                text="answer text",
                model="agent-builder:abc12345",
                citations=[],
            ),
            retrieved_count=3,
            latency_ms=150,
        )
        assert resp.question == "test"
        assert resp.answer.text == "answer text"
        assert resp.answer.model == "agent-builder:abc12345"
        assert resp.retrieved_count == 3
        assert resp.latency_ms == 150

    def test_response_with_citations(self):
        from uuid import uuid4
        citation = CitationSchema(
            chunk_id="chunk-1",
            document_id=str(uuid4()),
            title="Test Doc",
            url="https://example.com",
            source_type="FILE",
            source_id="README",
            chunk_index=0,
            total_chunks=1,
        )
        resp = ChatResponseSchema(
            question="test",
            answer=ChatAnswerSchema(
                text="answer",
                model="test-model",
                citations=[citation],
            ),
            retrieved_count=1,
            latency_ms=50,
        )
        assert len(resp.answer.citations) == 1
        assert resp.answer.citations[0].title == "Test Doc"

    def test_response_empty_citations_default(self):
        resp = ChatResponseSchema(
            question="test",
            answer=ChatAnswerSchema(text="answer", model="model"),
            retrieved_count=0,
            latency_ms=0,
        )
        assert resp.answer.citations == []
