from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentSchema(BaseModel):
    id: UUID
    title: str
    source_type: str
    source_id: str
    url: str | None = None
    created_at: datetime
    updated_at: datetime


class ListDocumentsResponseSchema(BaseModel):
    documents: list[DocumentSchema]
    total: int
    limit: int
    offset: int
