from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.ingest_job import IngestJobStatus


class CreateIngestJobRequest(BaseModel):
    source_type: SourceType
    stats: dict[str, Any] = Field(default_factory=dict)


class UpdateIngestJobRequest(BaseModel):
    status: IngestJobStatus | None = None
    completed_at: datetime | None = None
    error: str | None = None
    stats: dict[str, Any] | None = None


class IngestJobResponse(BaseModel):
    id: str
    source_type: SourceType
    status: IngestJobStatus
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
