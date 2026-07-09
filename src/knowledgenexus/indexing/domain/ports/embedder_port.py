from abc import ABC, abstractmethod

from knowledgenexus.indexing.domain.value_objects.embedding_vector import EmbeddingVector


class EmbedderPort(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> EmbeddingVector:
        ...
