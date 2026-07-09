from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from knowledgenexus.indexing.domain.enums import SourceType


@dataclass
class Document:
    title: str
    content: str
    source_type: SourceType
    source_id: str
    id: UUID = field(default_factory=uuid4)
    url: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def update_content(self, new_content: str) -> None:
        self.content = new_content
        self.updated_at = datetime.now()
    
    def update_metadata(self, new_metadata: dict[str, object]) -> None:
        self.metadata = new_metadata
        self.updated_at = datetime.now()
