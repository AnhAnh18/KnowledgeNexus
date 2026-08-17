from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from knowledgenexus.indexing.domain.enums.source_type import SourceType


class IngestJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class IngestJob:
    id: str
    source_type: SourceType
    status: IngestJobStatus
    started_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    stats: dict[str, object] = field(default_factory=dict)
    # Present only while this job owns an active Confluence subtree submission.
    # It is a database-unique, sanitized digest rather than a URL so duplicate
    # browser submissions cannot start concurrent crawls of the same root.
    active_key: str | None = None
