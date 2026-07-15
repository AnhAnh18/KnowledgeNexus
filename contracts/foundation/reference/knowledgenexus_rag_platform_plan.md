---
name: KnowledgeNexus RAG Platform
overview: "Clean Architecture RAG platform: hybrid storage từ đầu (SQLite + Qdrant), BGE-M3 local embedding, payload 2 tầng (CoreChunkMetadata + extra), roadmap 6 milestone; Docker đưa vào phase cuối (M6)."
todos:
  - id: m0-foundation
    content: "M0 — Foundation & Contract (Ryan/Bin): pyproject, contracts/, domain models, source_metadata schemas, all ports, config/qdrant.collection.yaml, ChunkStorageService facade (hybrid), OpenAPI — chưa Docker"
    status: completed
  - id: m1-qdrant
    content: "M1 — Core Storage (Ryan): SQLite repos (documents/chunks/jobs) + Qdrant adapter slim payload, payload indexes, store/search ports, Store API + health"
    status: completed
  - id: m2-ingestion
    content: "M2 — Ingestion Pipeline (Bin): chunker, BGE-M3 embedder, Confluence parser, metadata→extra mapping, ingest pipeline service"
    status: pending
  - id: m3-e2e-ingest
    content: "M3 — Integration MVP-1 (Ryan/Bin): Ingest + Store endpoints, E2E Confluence → SQLite + Qdrant, ingest job tracking"
    status: pending
  - id: m4-retrieval
    content: "M4 — Retrieval MVP-2 (Tez): Retrieve endpoint, Qdrant search + SQLite hydrate, document listing từ DB"
    status: pending
  - id: m5-chat
    content: "M5 — Chat MVP-3 (Tez): Gauss LLM adapter, RAG chat endpoint, citations"
    status: pending
  - id: m6-production
    content: "M6 — Production & Docker (Ryan/Bin/Tez): docker-compose, MCP/URL connectors, object storage, PostgreSQL migration path, CI/CD, hardening"
    status: pending
isProject: false
---

# Kế hoạch KnowledgeNexus — Clean Architecture + RAG

## Hiện trạng

Workspace [`KnowledgeNexus`](c:\Users\toan.pham\Documents\KnowledgeNexus) có skeleton Clean Architecture (~2% implemented):

- [`embedder_port.py`](c:\Users\toan.pham\Documents\KnowledgeNexus\packages\domain\src\knowledgenexus_domain\ports\embedder_port.py) — port embedding (broken import)
- [`extracted_document.py`](c:\Users\toan.pham\Documents\KnowledgeNexus\services\api\src\knowledgenexus\application\dto\extracted_document.py) — DTO stub (broken import)

Chưa có: contracts, dependency manifest, Docker, Qdrant client, parsers, API, tests.

**Dev local (M0–M5):** chạy Qdrant binary/native (`qdrant` hoặc download release) trên port 6333 — **không dùng Docker** cho đến M6.

---

## Quyết định kiến trúc (đã chốt)

| Thành phần | MVP (M0–M5) | Sau MVP (M6) |
|---|---|---|
| **Pattern** | Clean Architecture + RAG, layer separation, storage swap qua ports | Giữ nguyên |
| **Vector DB** | **Qdrant** — slim payload (refs + filter fields), vector search | Giữ nguyên; Docker compose |
| **Text DB** | **SQLite** — documents, chunks, ingest_jobs từ M1 | PostgreSQL migration path |
| **Embedding** | **BAAI/bge-m3** — multilingual (VI), local, free, 1024-dim | Giữ nguyên |
| **Object Storage** | **Không dùng trong MVP** | Local folder → S3/MinIO (M6) |
| **Backend** | Python / FastAPI | Giữ nguyên |
| **Generation LLM** | Gauss nội bộ (MVP-3) | Giữ nguyên |
| **Payload model** | **2 tầng:** `CoreChunkMetadata` (chung) + `extra` dict (riêng nguồn) | Typed schemas per source |
| **Docker** | **Không dùng** — Qdrant chạy native/local | `docker-compose.yml` full stack (M6) |

**Nguyên tắc MVP:** **Hybrid storage từ M1** — SQLite là source of truth cho document/chunk text + metadata; Qdrant chỉ lưu vector + slim payload (filter fields). `ChunkStorageService` facade che giấu chi tiết storage khỏi use cases.

---

## Payload & Metadata Model — Multi-Source

### Nguyên tắc thiết kế

```mermaid
flowchart LR
    Sources["Confluence / MD / MCP / URL / PDF / Image"]
    Parser["Parser / Connector"]
    Document["Document\n(common fields + metadata dict)"]
    Chunker["Chunker"]
    Chunk["Chunk\n(CoreChunkMetadata + content + extra dict)"]
    SQLite[("SQLite\nfull text + metadata")]
    Qdrant[("Qdrant\nvector + slim payload")]

    Sources --> Parser --> Document --> Chunker --> Chunk
    Chunk --> SQLite
    Chunk --> Qdrant
```

| Nguyên tắc | Mô tả |
|---|---|
| **Normalize sớm** | Mọi nguồn → cùng shape `Document` sau parser |
| **metadata → extra** | `Document.metadata` (dict) copy sang `ChunkPayload.extra` khi chunk |
| **Filter trên core** | Qdrant index chỉ các trường `CoreChunkMetadata` |
| **Mở rộng qua dict** | Thuộc tính riêng nguồn **không** thêm top-level payload key mới |
| **Typed validation** | `source_metadata/` định nghĩa schema per source; parser validate trước khi ghi |

> **Lưu ý:** Không có field tên `dist`. Dùng `metadata` (document level) và `extra` (chunk level) — cả hai là `dict[str, object]`.

### Tiêu chí phân loại field

| Loại field | Đặt ở đâu | Ví dụ |
|---|---|---|
| Filter / citation / re-sync / trace | **Core** (`CoreChunkMetadata`) | `source_type`, `source_id`, `title`, `url` |
| Hiển thị / debug / audit | **`metadata` / `extra`** | `version`, `author`, `mime_type` |
| Binary / file gốc | **Object storage** (M6) | PDF gốc, image gốc |
| Chỉ dùng lúc parse | **Parser internal** | raw HTML trước strip |

**Quy tắc nâng field từ `extra` lên `core`:** chỉ khi field đó được **filter thường xuyên** trong search (vd: `space_key` nếu luôn filter Confluence theo space).

### SourceType enum

```
CONFLUENCE | MCP | URL | FILE
```

| Nguồn thực tế | `source_type` | Ghi chú |
|---|---|---|
| Confluence / Wiki nội bộ | `CONFLUENCE` | Wiki Atlassian dùng chung parser |
| File `.md` | `FILE` | `extra.mime_type = "text/markdown"` |
| PDF | `FILE` | `extra.mime_type = "application/pdf"` |
| Image (OCR/vision) | `FILE` | `extra.mime_type = "image/png"`; text OCR → `content` |
| Link URL | `URL` | |
| MCP resource | `MCP` | |

### Trường chung — Document level

```python
@dataclass
class Document:
    id: UUID
    title: str
    content: str                     # text đã extract — input cho chunker
    source_type: SourceType
    source_id: str                   # page_id, url hash, file hash — re-sync key
    url: str | None
    metadata: dict[str, object]      # source-specific — parser output
    created_at: datetime
    updated_at: datetime
```

### Trường chung — Chunk level (`CoreChunkMetadata`)

```python
@dataclass
class CoreChunkMetadata:
    document_id: str
    source_type: SourceType
    source_id: str
    title: str
    url: str | None
    chunk_index: int
    total_chunks: int
    indexed_at: datetime
    embedding_model: str             # "BAAI/bge-m3"
```

### ChunkPayload

```python
@dataclass
class ChunkPayload:
    core: CoreChunkMetadata
    content: str                     # full chunk text (retrieval + display)
    extra: dict[str, object]         # copy từ Document.metadata + chunk-specific fields
```

### Luồng metadata → extra

```
Parser:
  Document.metadata = { space_key, version, ... }

Chunker:
  chunk.payload.extra = copy(document.metadata)
  + thêm field chunk-specific nếu có (vd: page_number cho PDF)

Store (ChunkStorageService):
  SQLite ← full ChunkPayload (content + core + extra)
  Qdrant ← vector + slim payload (core filter fields only)
```

### Source-specific schemas (`source_metadata/`)

Typed dataclasses/Pydantic models — parser validate, serialize thành `dict` khi ghi `metadata`/`extra`:

**`ConfluenceMetadata`**
```json
{ "space_key": "DEV", "page_id": "123456", "version": 3, "author": "user@co.com", "labels": ["deploy"], "parent_page_id": "789" }
```

**`FileMetadata`** (MD / PDF / Image)
```json
{ "file_path": "docs/rag.md", "mime_type": "text/markdown", "file_hash": "sha256:abc...", "frontmatter": { "tags": ["rag"] } }
```
```json
{ "file_path": "reports/q1.pdf", "mime_type": "application/pdf", "page_number": 5, "total_pages": 120, "file_hash": "sha256:def..." }
```
```json
{ "file_path": "diagrams/flow.png", "mime_type": "image/png", "width": 1920, "height": 1080, "ocr_engine": "tesseract", "alt_text": "..." }
```

**`UrlMetadata`**
```json
{ "canonical_url": "https://...", "domain": "example.com", "scraped_at": "...", "http_status": 200, "content_type": "text/html" }
```

**`McpMetadata`**
```json
{ "server_name": "linear-mcp", "resource_uri": "mcp://linear/issues/KN-42", "resource_type": "issue", "connector_version": "1.2.0" }
```

### ExtractedDocument DTO (parser → pipeline boundary)

```python
@dataclass
class ExtractedDocument:
    title: str
    content: str
    source_type: SourceType
    source_id: str
    url: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
```

---

## Clean Architecture — Project Structure (đề xuất chi tiết)

### Nguyên tắc phân layer

```mermaid
flowchart TB
    subgraph deps [Dependency Rule — chỉ hướng vào trong]
        Presentation["Presentation\n(FastAPI routes, schemas)"]
        Infrastructure["Infrastructure\n(Qdrant, SQLite, BGE-M3, parsers)"]
        Application["Application\n(use cases, DTOs, orchestration)"]
        Domain["Domain\n(entities, ports, enums)\nKHÔNG import layer ngoài"]
    end

    Presentation --> Application
    Infrastructure --> Application
    Infrastructure --> Domain
    Application --> Domain
```

| Layer | Vai trò | Được import | Không được import |
|-------|---------|-------------|-------------------|
| **Domain** | Entities, value objects, ports (interface) | Chỉ stdlib + domain nội bộ | FastAPI, Qdrant, SQLAlchemy, FlagEmbedding |
| **Application** | Use cases, orchestration, DTO | Domain | Infrastructure cụ thể |
| **Infrastructure** | Adapter implement ports | Domain + Application | Presentation |
| **Presentation** | HTTP, CLI, schemas | Application + Domain DTO | Trực tiếp Qdrant client |

**Monorepo layout:**

```
KnowledgeNexus/
│
├── contracts/                          # Biên giới team — KHÔNG phụ thuộc code
│   └── openapi.yaml                    # Ingest / Store / Retrieve / Chat
│
├── config/                             # Schema & default — commit vào git
│   ├── qdrant.collection.yaml          # Collection schema (vector size, indexes)
│   └── defaults.yaml                   # Default non-secret values
│
├── data/                               # Runtime data — GITIGNORE
│   ├── models/                         # HF cache override
│   ├── raw/                            # M6: object storage local
│   └── knowledgenexus.db               # SQLite — active từ M1
│
├── packages/domain/                    # Package độc lập — publishable
│   └── src/knowledgenexus_domain/
│       ├── entities/
│       │   ├── document.py
│       │   └── chunk.py                # Chunk, ChunkPayload, CoreChunkMetadata
│       ├── value_objects/
│       │   └── embedding_vector.py
│       ├── enums/
│       │   └── source_type.py
│       ├── source_metadata/            # Typed schemas per source
│       │   ├── confluence.py
│       │   ├── file.py                 # MD, PDF, Image
│       │   ├── url.py
│       │   └── mcp.py
│       ├── ports/
│       │   ├── embedder_port.py
│       │   ├── vector_store_port.py
│       │   ├── chunk_repository_port.py
│       │   ├── document_repository_port.py
│       │   ├── ingest_job_repository_port.py
│       │   ├── object_storage_port.py      # M6: stub → implement
│       │   ├── llm_port.py
│       │   └── source_connector_port.py
│       └── exceptions/
│
├── services/api/
│   └── src/knowledgenexus/
│       ├── application/
│       │   ├── dto/
│       │   ├── use_cases/
│       │   └── services/
│       │       ├── ingest_pipeline.py
│       │       └── chunk_storage_service.py  # Facade: SQLite + Qdrant
│       ├── infrastructure/
│       │   ├── config/
│       │   ├── embedding/
│       │   ├── vector_store/
│       │   ├── repositories/
│       │   │   ├── sqlite_document_repo.py   # M1
│       │   │   ├── sqlite_chunk_repo.py      # M1
│       │   │   ├── sqlite_ingest_job_repo.py # M1
│       │   │   └── postgres_*_repo.py        # M6 migration
│       │   ├── database/
│       │   │   ├── models.py                 # SQLAlchemy models
│       │   │   └── migrations/               # Alembic
│       │   ├── object_storage/               # M6
│       │   ├── chunking/
│       │   └── parsers/
│       └── presentation/
│
├── docker/                             # M6 only
│   ├── Dockerfile
│   └── qdrant/config.yaml
│
├── tests/
├── .env.example
├── docker-compose.yml                  # M6 only
└── pyproject.toml
```

### Dependency Injection — wiring adapters

```python
# STORAGE_MODE=hybrid (default từ M1)
# STORAGE_MODE=postgres (M6 — swap SQLite → PostgreSQL)

def get_chunk_storage() -> ChunkStorageService:
    return ChunkStorageService(
        vector_store=QdrantStore(...),
        chunk_repo=get_chunk_repo(),           # SQLite M1, Postgres M6
        document_repo=get_document_repo(),
    )
```

Use cases **chỉ** inject `ChunkStorageService` — không biết SQLite hay Qdrant.

---

## Data Placement — Mỗi loại dữ liệu lưu ở đâu?

### Bảng tổng hợp

| Loại dữ liệu | MVP (M1–M5) Hybrid | M6 mở rộng | Config / Code location |
|---|---|---|---|
| **Embedding model weights** | Cache local, không commit | Giữ nguyên | `EMBEDDING_CACHE_DIR` |
| **Embedding vectors** | **Qdrant** point vector | Giữ nguyên | `qdrant_store.py` |
| **Chunk full text** | **SQLite** `chunks.content` | PostgreSQL | `sqlite_chunk_repo.py` |
| **CoreChunkMetadata** | **SQLite** `chunks.core_metadata` JSON | PostgreSQL columns | `entities/chunk.py` |
| **ChunkPayload.extra** | **SQLite** `chunks.extra` JSON | PostgreSQL JSONB | `source_metadata/` |
| **Document registry** | **SQLite** `documents` table | PostgreSQL | `sqlite_document_repo.py` |
| **Ingest jobs** | **SQLite** `ingest_jobs` table | PostgreSQL | `sqlite_ingest_job_repo.py` |
| **Qdrant slim payload** | `chunk_id`, `document_id`, `source_type`, `source_id`, `chunk_index` | Giữ nguyên | `qdrant_store.py` |
| **Raw source files** | Không lưu (re-fetch) | **Object storage** | M6: `ObjectStoragePort` |
| **Qdrant server** | Native binary local :6333 | **Docker** container | M6: `docker-compose.yml` |

### Hybrid storage flow

```mermaid
flowchart TB
    Chunk[Chunk entity]
    Chunk --> SQLite[("SQLite\nchunks + documents + jobs")]
    Chunk --> QdrantSlim["Qdrant\nvector + slim payload"]

    Retrieve[Retrieve flow] --> QdrantSlim
    QdrantSlim -->|"chunk_ids + scores"| SQLite
    SQLite -->|"full content + extra"| Response
```

```python
class ChunkStorageService:
    async def save(self, chunks: list[Chunk]) -> None:
        await self._chunk_repo.save_batch(chunks)      # SQLite first (source of truth)
        await self._vector_store.upsert_slim(chunks)   # Qdrant refs + vector

    async def get_by_ids(self, chunk_ids: list[UUID]) -> list[Chunk]:
        return await self._chunk_repo.get_by_ids(chunk_ids)

    async def search(self, query_vector, top_k, filters) -> list[ScoredChunk]:
        slim_results = await self._vector_store.search(query_vector, top_k, filters)
        return await self._chunk_repo.hydrate(slim_results)  # Join full text from SQLite
```

### SQLite schema (M1 — active từ đầu)

```sql
documents (
  id TEXT PK, title TEXT, source_type TEXT, source_id TEXT,
  url TEXT, metadata JSON, created_at DATETIME, updated_at DATETIME
)
-- UNIQUE(source_type, source_id) — idempotent re-sync

chunks (
  id TEXT PK, document_id TEXT FK, chunk_index INT,
  content TEXT, core_metadata JSON, extra JSON, indexed_at DATETIME
)

ingest_jobs (
  id TEXT PK, source_type TEXT, status TEXT,
  started_at DATETIME, completed_at DATETIME,
  error TEXT, stats JSON
)
```

Port: `ChunkRepositoryPort` + `DocumentRepositoryPort` + `IngestJobRepositoryPort` — implement `sqlite_*` ở M1; swap `postgres_*` ở M6.

### Qdrant slim payload (M1+)

```json
{
  "id": "uuid-chunk-id",
  "vector": [1024 floats],
  "payload": {
    "chunk_id": "uuid-chunk-id",
    "document_id": "uuid",
    "source_type": "CONFLUENCE",
    "source_id": "123456",
    "chunk_index": 0,
    "indexed_at": "2026-07-07T..."
  }
}
```

**Payload indexes:**
- `source_type` — keyword
- `source_id` — keyword
- `document_id` — keyword
- `chunk_id` — keyword
- `indexed_at` — datetime

Full `content`, `title`, `url`, `extra` → **chỉ trong SQLite**, hydrate sau search.

### Object storage layout (M6)

```
data/raw/
  confluence/{page_id}/raw.html
  url/{url_hash}/raw.html
  mcp/{server_name}/{resource_id}/raw.txt
  file/{document_id}/original.pdf
```

---

## System Architecture

```mermaid
flowchart TB
    subgraph sources [Data Sources]
        Confluence[Confluence / Wiki]
        MCP[MCP Servers]
        URL[Web Links]
        Files[MD / PDF / Image]
    end

    subgraph app [FastAPI Application]
        IngestAPI[Ingest API]
        RetrieveAPI[Retrieve API]
        ChatAPI[Chat API]
        IngestUC[IngestUseCase]
        RetrieveUC[RetrieveUseCase]
        ChatUC[ChatUseCase]
        Parsers[Source Parsers]
        Chunker[TextChunker]
        Embedder[BgeM3Embedder]
        StorageFacade[ChunkStorageService]
    end

    subgraph storage [Storage — Hybrid từ M1]
        SQLite[("SQLite\nM1+")]
        Qdrant[("Qdrant\nM1+ native")]
        LocalFolder[("Object Storage\nM6")]
    end

    sources --> Parsers --> IngestUC --> Chunker --> Embedder --> StorageFacade
    StorageFacade --> SQLite
    StorageFacade --> Qdrant
    RetrieveUC --> StorageFacade
    ChatUC --> RetrieveUC
    IngestAPI --> IngestUC
    RetrieveAPI --> RetrieveUC
    ChatAPI --> ChatUC
    LocalFolder -.-> M6
```

---

## API Contract — 4 endpoint groups

Định nghĩa OpenAPI trong [`contracts/openapi.yaml`](c:\Users\toan.pham\Documents\KnowledgeNexus\contracts\openapi.yaml) (M0).

### 1. Ingest

| Method | Endpoint | Mô tả | Milestone |
|--------|----------|-------|-----------|
| POST | `/api/v1/ingest/confluence` | Sync Confluence space/pages | M3 |
| POST | `/api/v1/ingest/url` | Ingest URL list | M6 |
| POST | `/api/v1/ingest/mcp` | Sync MCP sources | M6 |
| POST | `/api/v1/ingest/file` | Upload MD/PDF/Image | M6 |
| GET | `/api/v1/ingest/jobs/{job_id}` | Job status | M3 (SQLite) |

### 2. Store

| Method | Endpoint | Mô tả | Milestone |
|--------|----------|-------|-----------|
| POST | `/api/v1/store/chunks` | Upsert chunks (testing) | M1 |
| DELETE | `/api/v1/store/documents/{document_id}` | Xóa chunks + vectors | M1 |
| GET | `/api/v1/store/stats` | Collection + DB stats | M1 |

### 3. Retrieve

| Method | Endpoint | Mô tả | Milestone |
|--------|----------|-------|-----------|
| POST | `/api/v1/retrieve/search` | Semantic search + hydrate | M4 |
| GET | `/api/v1/retrieve/documents` | List từ SQLite documents | M4 |
| GET | `/api/v1/retrieve/documents/{document_id}/chunks` | Chunks từ SQLite | M4 |

**Search response** trả `content`, `title`, `url`, `extra` sau hydrate từ SQLite.

### 4. Chat

| Method | Endpoint | Mô tả | Milestone |
|--------|----------|-------|-----------|
| POST | `/api/v1/chat` | RAG chat + citations | M5 |
| POST | `/api/v1/chat/stream` | Streaming | M5 (optional) |

### Health

| GET | `/api/v1/health` | API + Qdrant + SQLite status | M1 |

---

## Sequence Diagrams

### Ingest Flow (M3 — MVP-1)

```mermaid
sequenceDiagram
    participant Client
    participant IngestAPI
    participant IngestUC as IngestUseCase
    participant Parser as ConfluenceParser
    participant Chunker
    participant Embedder as BgeM3Embedder
    participant Storage as ChunkStorageService
    participant SQLite
    participant Qdrant

    Client->>IngestAPI: POST /ingest/confluence
    IngestAPI->>IngestUC: execute(space_key)
    IngestUC->>SQLite: create ingest_job (pending)
    IngestUC->>Parser: fetch_pages(space_key)
    Parser-->>IngestUC: list[Document + metadata]

    loop each Document
        IngestUC->>Chunker: split(content) → extra = copy(metadata)
        Chunker-->>IngestUC: list[Chunk]
        IngestUC->>Embedder: embed(chunks.content)
        Embedder-->>IngestUC: list[EmbeddingVector]
        IngestUC->>Storage: save(chunks)
        Storage->>SQLite: upsert documents + chunks
        Storage->>Qdrant: delete_by_source_id then upsert_slim
    end

    IngestUC->>SQLite: update ingest_job (completed)
    IngestAPI-->>Client: 200 { job_id, documents_ingested, chunks_created }
```

### Retrieve Flow (M4 — MVP-2)

```mermaid
sequenceDiagram
    participant Client
    participant RetrieveAPI
    participant RetrieveUC as RetrieveUseCase
    participant Embedder as BgeM3Embedder
    participant Qdrant
    participant SQLite

    Client->>RetrieveAPI: POST /retrieve/search
    RetrieveUC->>Embedder: embed_query(query)
    RetrieveUC->>Qdrant: search(vector, filters) → slim results
    RetrieveUC->>SQLite: hydrate(chunk_ids) → full content + extra
    RetrieveAPI-->>Client: 200 { results[] with content, extra }
```

---

## Team Roadmap — 6 Milestones

| # | Milestone | Owner | Deliverable | MVP |
|---|-----------|-------|-------------|-----|
| **0** | Foundation & Contract | Ryan / Bin | Domain models, `source_metadata/`, ports, OpenAPI, hybrid `ChunkStorageService` interface — **no Docker** | Contract OK |
| **1** | Core Storage | Ryan | **SQLite repos** + Qdrant slim adapter, Store API, health, Alembic migrations | — |
| **2** | Ingestion Pipeline | Bin | Chunker, BGE-M3, Confluence parser, metadata→extra mapping | — |
| **3** | Integration | Ryan / Bin | **MVP-1:** Confluence → SQLite + Qdrant, ingest job tracking | MVP-1 |
| **4** | Retrieval | Tez | **MVP-2:** Search + SQLite hydrate, document listing từ DB | MVP-2 |
| **5** | Chat | Tez | **MVP-3:** Gauss RAG chat + citations | MVP-3 |
| **6** | Production & Docker | Ryan / Bin / Tez | **Docker compose**, MCP/URL/file connectors, object storage, PostgreSQL, CI/CD | Post-MVP |

### Dependency graph

```mermaid
flowchart LR
    M0[M0 Foundation] --> M1[M1 Core Storage\nSQLite + Qdrant]
    M0 --> M2[M2 Ingestion Pipeline]
    M1 --> M3[M3 MVP-1 Ingest E2E]
    M2 --> M3
    M1 --> M4[M4 MVP-2 Search]
    M2 --> M4
    M4 --> M5[M5 MVP-3 RAG Chat]
    M5 --> M6[M6 Docker + Production]
```

---

## Chi tiết từng milestone

### M0 — Foundation & Contract (Ryan / Bin)

- `pyproject.toml` monorepo (`knowledgenexus-domain`, `knowledgenexus-api`)
- Domain entities: `Document`, `Chunk`, `ChunkPayload`, `CoreChunkMetadata`
- `source_metadata/`: typed schemas — `ConfluenceMetadata`, `FileMetadata`, `UrlMetadata`, `McpMetadata`
- `SourceType` enum: `CONFLUENCE | MCP | URL | FILE`
- All ports defined: `VectorStorePort`, `ChunkRepositoryPort`, `DocumentRepositoryPort`, `IngestJobRepositoryPort`, `ObjectStoragePort` (no-op stub)
- [`contracts/openapi.yaml`](c:\Users\toan.pham\Documents\KnowledgeNexus\contracts\openapi.yaml) — 4 endpoint groups + payload schemas (`CoreChunkMetadata`, `extra`)
- [`config/qdrant.collection.yaml`](c:\Users\toan.pham\Documents\KnowledgeNexus\config\qdrant.collection.yaml) — slim payload indexes
- `infrastructure/config/settings.py` — `STORAGE_MODE=hybrid`, `DATABASE_URL=sqlite:///./data/knowledgenexus.db`
- `ChunkStorageService` facade interface (implement ở M1)
- **Không tạo Docker** — document hướng dẫn cài Qdrant native trong README
- Fix broken imports trong 2 file hiện có

### M1 — Core Storage (Ryan)

- SQLAlchemy models + Alembic migrations: `documents`, `chunks`, `ingest_jobs`
- `SqliteDocumentRepo`, `SqliteChunkRepo`, `SqliteIngestJobRepo`
- `QdrantVectorStore` implements `VectorStorePort` — slim payload only
- `ChunkStorageService` full implement: save (SQLite → Qdrant), search + hydrate
- Operations: `upsert_slim`, `search`, `delete_by_source_id`, `get_stats`
- Store API + health (Qdrant + SQLite connectivity)
- Integration test: round-trip save → search → hydrate

### M2 — Ingestion Pipeline (Bin)

- `BgeM3Embedder` — FlagEmbedding, lazy-load, batch embed
- `RecursiveChunker` — 1500 chars, overlap 150
- `ConfluenceParser` → `ExtractedDocument` với `ConfluenceMetadata` validated → `metadata` dict
- Metadata→extra mapping trong chunker/pipeline
- `IngestPipelineService` — parse → chunk → embed (no storage)

### M3 — Integration / MVP-1 (Ryan / Bin)

- `IngestDocumentUseCase` + wired `ChunkStorageService`
- `POST /api/v1/ingest/confluence` — full E2E
- `GET /api/v1/ingest/jobs/{job_id}` — status từ SQLite
- Idempotent re-sync: `UNIQUE(source_type, source_id)` + delete old chunks/vectors
- Integration test: Confluence page → SQLite rows + Qdrant points

### M4 — Retrieval / MVP-2 (Tez)

- `RetrieveSimilarUseCase` — embed query → Qdrant search → SQLite hydrate
- `POST /api/v1/retrieve/search` — trả `content`, `title`, `url`, `extra`, `score`
- `GET /api/v1/retrieve/documents` — từ SQLite `documents` table
- `GET /api/v1/retrieve/documents/{id}/chunks` — từ SQLite `chunks`

### M5 — Chat / MVP-3 (Tez)

- `GaussLLMAdapter` implements `LLMPort`
- `ChatRagUseCase` — retrieve → prompt → generate → cite sources (title, url từ SQLite)
- `POST /api/v1/chat` — RAG response with citations
- Unit + integration tests

### M6 — Production & Docker (Ryan / Bin / Tez)

- **`docker-compose.yml`**: Qdrant container + API container + volume mounts
- `docker/Dockerfile` + `docker/qdrant/config.yaml`
- **PostgreSQL** migration path: `postgres_*_repo.py` swap qua `STORAGE_MODE=postgres`
- **Local folder** object storage (raw HTML/PDF/image)
- Parsers/connectors: MCP, URL scraper, file upload (MD/PDF/image + OCR stub)
- `POST /api/v1/ingest/file`, `/ingest/url`, `/ingest/mcp`
- Streaming chat, auth, rate limiting, CI/CD
- Production hardening: backup SQLite/Postgres, Qdrant snapshot

---

## Config môi trường (`.env.example`)

```env
# Storage
STORAGE_MODE=hybrid                   # hybrid (default) | postgres (M6)
DATABASE_URL=sqlite:///./data/knowledgenexus.db

# Qdrant — native local M0-M5; Docker M6
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=knowledgenexus

# Embedding
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=cpu
EMBEDDING_CACHE_DIR=./data/models
EMBEDDING_BATCH_SIZE=32

# Confluence (M3)
CONFLUENCE_BASE_URL=https://your-domain.atlassian.net/wiki
CONFLUENCE_EMAIL=your-email@company.com
CONFLUENCE_API_TOKEN=your-api-token

# Gauss LLM (M5)
GAUSS_BASE_URL=https://gauss-internal.company.com/v1
GAUSS_API_KEY=your-gauss-api-key
GAUSS_MODEL=gauss-language

# M6 only
# DATABASE_URL=postgresql://user:pass@localhost/knowledgenexus
OBJECT_STORAGE_PATH=./data/raw
```

---

## Rủi ro và giải pháp

| Rủi ro | Giải pháp |
|--------|-----------|
| SQLite write contention khi ingest song song | WAL mode; batch insert; job queue nếu cần |
| Hydrate latency sau Qdrant search | Batch `get_by_ids`; index `chunks.id` PK |
| Qdrant chưa có Docker ở M0–M5 | Document cài native binary; health check rõ ràng |
| BGE-M3 chậm trên CPU i7 | Batch 32 chunks; lazy-load; ~2GB RAM |
| Gauss API format chưa rõ | `LLMPort` + configurable adapter |
| `extra` dict không typed ở runtime | `source_metadata/` validate lúc parse; optional JSON schema trong OpenAPI |
| Team parallel conflicts | M0 contract trước; M1/M2 song song; M3 cần M1+M2 |

---

## Kết quả theo MVP

| MVP | Có thể làm được |
|-----|-----------------|
| **MVP-1** (M3) | Sync Confluence → SQLite + Qdrant, ingest job tracking |
| **MVP-2** (M4) | Semantic search (Qdrant) + full payload hydrate (SQLite), list documents |
| **MVP-3** (M5) | RAG chat với Gauss + citations (title, url, extra) |
| **Post-MVP** (M6) | Docker compose, MCP/URL/file ingest, object storage, PostgreSQL |
