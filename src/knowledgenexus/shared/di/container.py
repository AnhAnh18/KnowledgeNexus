from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowledgenexus.foundation.infrastructure.config.chunking_profile_loader import (
    load_chunking_profile,
)
from knowledgenexus.foundation.infrastructure.processors import (
    ConfluenceDataCenterRawPageMapper,
    ConfluenceStorageXhtmlNormalizer,
)
from knowledgenexus.foundation.infrastructure.raw_store import ConfluenceRawPageGenerationStore
from knowledgenexus.foundation.infrastructure.tokenization import BgeM3LocalTokenizer
from knowledgenexus.indexing.application.use_cases.chunk_storage_service import ChunkStorageService
from knowledgenexus.indexing.application.use_cases.ingest_confluence_page import (
    IngestConfluencePage,
)
from knowledgenexus.indexing.application.use_cases.ingest_confluence_page_from_url import (
    IngestConfluencePageFromUrl,
)
from knowledgenexus.indexing.application.use_cases.ingest_confluence_subtree_from_url import (
    IngestConfluenceSubtreeFromUrl,
)
from knowledgenexus.indexing.application.use_cases.ingest_chunking_packet import IngestChunkingPacket
from knowledgenexus.indexing.infrastructure.embedding.bge_m3_embedder import BgeM3Embedder
from knowledgenexus.retrieval.domain.ports.reranker_port import RerankerPort
from knowledgenexus.retrieval.infrastructure.reranking.bge_reranker import BgeReranker
from knowledgenexus.shared.config.settings import Settings
from knowledgenexus.shared.contracts.foundation.schema_validator import (
    FoundationSchemaValidator,
)
from knowledgenexus.indexing.infrastructure.database.engine import create_engine, create_session_factory, init_database
from knowledgenexus.indexing.infrastructure.repositories.sqlite_chunk_repo import SqliteChunkRepository
from knowledgenexus.indexing.infrastructure.repositories.sqlite_document_repo import SqliteDocumentRepository
from knowledgenexus.indexing.infrastructure.repositories.sqlite_ingest_job_repo import SqliteIngestJobRepository
from knowledgenexus.indexing.infrastructure.vector_store.qdrant_store import QdrantVectorStore


@dataclass
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    chunk_repo: SqliteChunkRepository
    document_repo: SqliteDocumentRepository
    ingest_job_repo: SqliteIngestJobRepository
    vector_store: QdrantVectorStore
    chunk_storage: ChunkStorageService
    embedder: BgeM3Embedder | None = field(default=None, repr=False, compare=False)
    reranker: RerankerPort | None = field(default=None, repr=False, compare=False)
    confluence_page_ingestor: IngestConfluencePageFromUrl | None = field(
        default=None, repr=False, compare=False
    )
    confluence_subtree_ingestor: IngestConfluenceSubtreeFromUrl | None = field(
        default=None, repr=False, compare=False
    )

    def get_embedder(self) -> BgeM3Embedder:
        if self.embedder is None:
            self.embedder = BgeM3Embedder.from_settings(self.settings)
        return self.embedder

    def get_reranker(self) -> RerankerPort | None:
        if self.reranker is None and self.settings.reranker_enabled:
            self.reranker = BgeReranker.from_settings(self.settings)
        return self.reranker

    def get_confluence_page_ingestor(self) -> IngestConfluencePageFromUrl:
        if self.confluence_page_ingestor is None:
            if not self.settings.confluence_base_url or not self.settings.confluence_pat:
                raise RuntimeError(
                    "CONFLUENCE_BASE_URL and CONFLUENCE_PAT must be set in .env "
                    "to ingest a Confluence page from a URL"
                )
            if not self.settings.embedding_model_path:
                raise RuntimeError(
                    "EMBEDDING_MODEL_PATH must be set in .env (BGE-M3 tokenizer assets dir)"
                )
            profile = load_chunking_profile(
                Path(self.settings.confluence_chunking_profile_path).resolve()
            )
            tokenizer = BgeM3LocalTokenizer(
                profile=profile,
                tokenizer_assets_dir=Path(self.settings.embedding_model_path),
            )
            raw_root = Path(self.settings.confluence_raw_root).resolve()
            raw_root.mkdir(parents=True, exist_ok=True)
            page_ingestor = IngestConfluencePage(
                chunking_profile=profile,
                tokenizer=tokenizer,
                raw_page_store=ConfluenceRawPageGenerationStore(raw_root=raw_root),
                raw_page_mapper=ConfluenceDataCenterRawPageMapper(),
                storage_normalizer=ConfluenceStorageXhtmlNormalizer(),
                schema_validator=FoundationSchemaValidator(),
                embedder=self.get_embedder(),
                chunk_storage_service=self.chunk_storage,
            )
            self.confluence_page_ingestor = IngestConfluencePageFromUrl(
                base_url=self.settings.confluence_base_url,
                pat=self.settings.confluence_pat,
                raw_root=raw_root,
                page_ingestor=page_ingestor,
            )
        return self.confluence_page_ingestor

    def get_confluence_subtree_ingestor(self) -> IngestConfluenceSubtreeFromUrl:
        if self.confluence_subtree_ingestor is None:
            if not self.settings.confluence_base_url or not self.settings.confluence_pat:
                raise RuntimeError("Confluence credentials are not configured")
            if not self.settings.embedding_model_path:
                raise RuntimeError("BGE-M3 tokenizer assets are not configured")
            self.confluence_subtree_ingestor = IngestConfluenceSubtreeFromUrl(
                snapshot_root=Path(self.settings.confluence_snapshot_root).resolve(),
                tokenizer_assets_dir=Path(self.settings.embedding_model_path).resolve(),
                max_pages=self.settings.confluence_max_pages,
                confluence_pat=self.settings.confluence_pat,
                packet_ingestor=IngestChunkingPacket(
                    embedder=self.get_embedder(), chunk_storage_service=self.chunk_storage,
                ),
            )
        return self.confluence_subtree_ingestor

    async def shutdown(self) -> None:
        if self.embedder is not None:
            self.embedder.close()
        if self.reranker is not None:
            self.reranker.close()
        await self.vector_store.close()
        await self.engine.dispose()


_container: AppContainer | None = None


async def build_container(settings: Settings) -> AppContainer:
    engine = create_engine(settings.database_url)
    await init_database(engine)
    session_factory = create_session_factory(engine)

    chunk_repo = SqliteChunkRepository(session_factory)
    document_repo = SqliteDocumentRepository(session_factory)
    ingest_job_repo = SqliteIngestJobRepository(session_factory)

    vector_store = await QdrantVectorStore.create(
        url=settings.qdrant_url,
        config_path=str(settings.qdrant_collection_config_path),
        api_key=settings.qdrant_api_key,
        collection_name_override=settings.qdrant_collection,
    )

    chunk_storage = ChunkStorageService(
        vector_store=vector_store,
        chunk_repo=chunk_repo,
        document_repo=document_repo,
    )

    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        chunk_repo=chunk_repo,
        document_repo=document_repo,
        ingest_job_repo=ingest_job_repo,
        vector_store=vector_store,
        chunk_storage=chunk_storage,
    )


async def init_container(settings: Settings) -> AppContainer:
    global _container
    _container = await build_container(settings)
    return _container


def get_container() -> AppContainer:
    if _container is None:
        raise RuntimeError("App container not initialized")
    return _container


async def shutdown_container() -> None:
    global _container
    if _container is not None:
        await _container.shutdown()
        _container = None
