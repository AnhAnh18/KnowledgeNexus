from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.document import Document
from knowledgenexus.indexing.domain.ports.document_repository_port import DocumentRepositoryPort

from knowledgenexus.indexing.infrastructure.database.mappers import document_from_model, document_to_model
from knowledgenexus.indexing.infrastructure.database.models import DocumentModel


class SqliteDocumentRepository(DocumentRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save(self, document: Document) -> None:
        model = document_to_model(document)
        async with self._session_factory() as session:
            stmt = sqlite_insert(DocumentModel).values(
                id=model.id,
                title=model.title,
                source_type=model.source_type,
                source_id=model.source_id,
                url=model.url,
                metadata_json=model.metadata_json,
                created_at=model.created_at,
                updated_at=model.updated_at,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[DocumentModel.id],
                set_={
                    "title": model.title,
                    "source_type": model.source_type,
                    "source_id": model.source_id,
                    "url": model.url,
                    "metadata": model.metadata_json,
                    "updated_at": model.updated_at,
                },
            )
            await session.execute(stmt)
            await session.commit()

    async def get_by_id(self, document_id: str) -> Document | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DocumentModel).where(DocumentModel.id == document_id)
            )
            model = result.scalar_one_or_none()
            return document_from_model(model) if model else None

    async def get_by_source(self, source_type: SourceType, source_id: str) -> Document | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DocumentModel).where(
                    DocumentModel.source_type == str(source_type),
                    DocumentModel.source_id == source_id,
                )
            )
            model = result.scalar_one_or_none()
            return document_from_model(model) if model else None

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[Document]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DocumentModel).order_by(DocumentModel.updated_at.desc()).limit(limit).offset(offset)
            )
            return [document_from_model(m) for m in result.scalars().all()]

    async def delete(self, document_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(DocumentModel).where(DocumentModel.id == document_id)
            )
            await session.commit()
            return (result.rowcount or 0) > 0

    async def count(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(select(func.count()).select_from(DocumentModel))
            return int(result.scalar_one())
