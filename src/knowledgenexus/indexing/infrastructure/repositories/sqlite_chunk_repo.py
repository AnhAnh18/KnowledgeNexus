from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowledgenexus.indexing.domain.enums.source_type import SourceType
from knowledgenexus.indexing.domain.models.chunk import Chunk
from knowledgenexus.indexing.domain.ports.chunk_repository_port import ChunkRepositoryPort
from knowledgenexus.indexing.domain.value_objects.scored_chunk import ScoredChunk

from knowledgenexus.indexing.infrastructure.database.mappers import chunk_from_model, chunk_to_model
from knowledgenexus.indexing.infrastructure.database.models import ChunkModel


class SqliteChunkRepository(ChunkRepositoryPort):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_batch(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        async with self._session_factory() as session:
            for chunk in chunks:
                model = chunk_to_model(chunk)
                stmt = sqlite_insert(ChunkModel).values(
                    id=model.id,
                    document_id=model.document_id,
                    chunk_index=model.chunk_index,
                    content=model.content,
                    core_metadata=model.core_metadata,
                    extra=model.extra,
                    indexed_at=model.indexed_at,
                    source_type=model.source_type,
                    source_id=model.source_id,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[ChunkModel.id],
                    set_={
                        "content": model.content,
                        "core_metadata": model.core_metadata,
                        "extra": model.extra,
                        "indexed_at": model.indexed_at,
                        "source_type": model.source_type,
                        "source_id": model.source_id,
                    },
                )
                await session.execute(stmt)
            await session.commit()

    async def get_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(select(ChunkModel).where(ChunkModel.id.in_(chunk_ids)))
            models = result.scalars().all()
        by_id = {m.id: chunk_from_model(m) for m in models}
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    async def get_by_document_id(self, document_id: str) -> list[Chunk]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .order_by(ChunkModel.chunk_index)
            )
            return [chunk_from_model(m) for m in result.scalars().all()]

    async def delete_by_source_id(self, source_type: SourceType, source_id: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ChunkModel).where(
                    ChunkModel.source_type == str(source_type),
                    ChunkModel.source_id == source_id,
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def delete_by_document_id(self, document_id: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                delete(ChunkModel).where(ChunkModel.document_id == document_id)
            )
            await session.commit()
            return result.rowcount or 0

    async def hydrate(self, slim_results: list[ScoredChunk]) -> list[ScoredChunk]:
        if not slim_results:
            return []
        chunk_ids = [r.chunk.id for r in slim_results]
        full_chunks = await self.get_by_ids(chunk_ids)
        chunk_map = {c.id: c for c in full_chunks}
        return [
            ScoredChunk(chunk=chunk_map[r.chunk.id], score=r.score)
            for r in slim_results
            if r.chunk.id in chunk_map
        ]

    async def count(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(select(func.count()).select_from(ChunkModel))
            return int(result.scalar_one())
