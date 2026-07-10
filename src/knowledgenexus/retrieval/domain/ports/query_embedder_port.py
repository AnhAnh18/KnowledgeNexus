from __future__ import annotations

from abc import ABC, abstractmethod

from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector


class QueryEmbedderPort(ABC):

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> EmbeddingVector:
        ...
