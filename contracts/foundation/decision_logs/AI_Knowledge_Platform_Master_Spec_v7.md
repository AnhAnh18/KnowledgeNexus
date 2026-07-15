**AI Knowledge Platform  
Master Specification v7**

*Organization Knowledge Platform for Confluence, Git/Gerrit, Jira, Source Code, Media, and Future MCP*

| **Field**                      | **Value**                                                       |
|--------------------------------|-----------------------------------------------------------------|
| Version                        | v7                                                              |
| Language of document           | English                                                         |
| Conversation language          | Vietnamese                                                      |
| Primary owner scope            | Part 1 — Knowledge Foundation / Data Collection & Preprocessing |
| Confirmed POC Confluence scope | Space/folder: SVMC; parent page id: 938880621                   |
| Confirmed POC repository       | spensdk                                                         |
| Jira status                    | No PAT yet; extract Jira keys by regex in POC                   |
| Current crawler identity       | Personal PAT for POC; service account recommended later         |

# Document Map

- 1\. Executive Summary

- 2\. Why v7 Exists

- 3\. Confirmed Decisions and POC Scope

- 4\. Whole Platform vs Part 1 Responsibility

- 5\. Business Problem and Why Confluence Matters

- 6\. GitAI Reference: What to Learn and What Not to Copy

- 7\. Architecture Overview

- 8\. Part 1 Module Structure

- 9\. Confluence Scope Filtering Strategy

- 10\. Confluence Connector MVP

- 11\. Media and Attachment Ingestion Strategy

- 12\. Git / spensdk Connector and Minimal Symbol Index

- 13\. Jira Key Extraction Without Jira PAT

- 14\. ACL and Security Model

- 15\. Storage Strategy

- 16\. Output Contract to Task 2 and Task 3

- 17\. Qdrant Integration Contract

- 18\. Sync, Rate Limit, and Resumability

- 19\. POC Build Order and Acceptance Criteria

- 20\. Risks, Non-Goals, and Open Questions

# 1. Executive Summary

**This document updates the project direction from a narrow data collection pipeline into an Organization Knowledge Platform.** The platform must collect, normalize, preserve, connect, and prepare internal engineering knowledge from Confluence, GitHub Enterprise/Gerrit, Jira, source code, media attachments, and future sources such as Figma or MCP.

The immediate owner scope is Part 1: Knowledge Foundation. Part 1 does not build the final chatbot. It creates reliable, structured, permission-aware, relation-aware, and chunk-ready datasets that Task 2 and Task 3 can use for embeddings, Qdrant retrieval, RAG, reports, agents, and future MCP exposure.

The first POC should be deliberately small but end-to-end: one Confluence scope, one large repository, local raw storage, JSONL export, Jira key extraction by regex, and a minimal code symbol index. The confirmed POC source is Confluence space/folder SVMC under parent page id 938880621 and the spensdk repository.

# 2. Why v7 Exists

Earlier versions were useful but split into two mental models. v4 contained detailed Task 1 implementation depth. v6 reset the architecture toward a broader platform. v7 merges those directions: it keeps the platform vision from v6 while restoring the implementation depth, module structure, data contracts, and POC-level clarity needed by an engineering team starting from zero.

| **Version** | **Role**                   | **Limitation**                                                                                      | **v7 Action**                                                              |
|-------------|----------------------------|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| v4          | Detailed Task 1 foundation | Focused on data collection before the Organization Knowledge Platform direction was fully confirmed | Reuse its depth around schema, chunking, quality gates, and Task 1 handoff |
| v5          | Short implementation plan  | Too short for handoff or implementation                                                             | Do not use as master spec                                                  |
| v6          | Architecture reset         | Strong platform direction but not enough module/POC detail                                          | Use as architectural base                                                  |
| v7          | Merged master spec         | Current planning draft                                                                              | Whole platform context + Part 1 actionable plan                            |

# 3. Confirmed Decisions and POC Scope

| **Topic**            | **Decision**                                                                                                                    |
|----------------------|---------------------------------------------------------------------------------------------------------------------------------|
| Product direction    | Organization Knowledge Platform, not only a chatbot                                                                             |
| Part 1 role          | Knowledge Foundation / Data Collection & Preprocessing                                                                          |
| POC Confluence scope | Space/folder SVMC, parent page id 938880621                                                                                     |
| POC repository       | spensdk                                                                                                                         |
| Jira access          | No Jira PAT yet; extract Jira keys by regex initially                                                                           |
| Storage              | Local POC; design interfaces for future internal server                                                                         |
| Output               | JSONL files + manifest + quality report                                                                                         |
| Code indexing        | Minimal symbol index is required for code Q&A Level B                                                                           |
| Media                | Crawl attachment metadata; download/process draw.io/PDF/image only when parent/child page is relevant; skip/defer video content |
| Confluence filtering | Use page ID tree scope as primary; keywords only as secondary signal                                                            |
| Rate limit           | Request 100 requests/min for initial sync if possible; crawler must still work at 20 requests/min                               |
| ACL                  | Store ACL/restriction metadata from the beginning                                                                               |
| PAT                  | Use personal PAT for POC; service account later                                                                                 |

# 4. Whole Platform vs Part 1 Responsibility

The module structure must be separated into two layers: the whole product architecture and the scope that this owner/team is responsible for now. This avoids accidentally building the chatbot, agent layer, or production UI before the data foundation is reliable.

![](media/image1.png)

Figure 1. Whole Platform Architecture

| **Area**              | **Owned by Part 1?**             | **Notes**                                           |
|-----------------------|----------------------------------|-----------------------------------------------------|
| Source connectors     | Yes                              | Confluence, Git/Gerrit, Jira later, media inventory |
| Raw store             | Yes                              | Preserve original responses and downloaded files    |
| Canonical schema      | Yes                              | Document/chunk/relation/ACL/symbol models           |
| Chunking              | Yes                              | Prepare Task 2 input                                |
| Embedding             | No                               | Task 2                                              |
| Qdrant index creation | No, but prepare payload contract | Task 2 can own upsert and retrieval optimization    |
| RAG answer generation | No                               | Task 3                                              |
| Chat UI / API         | No for POC                       | Optional debug CLI only                             |
| MCP endpoint          | No for POC                       | Future platform layer                               |

# 5. Business Problem and Why Confluence Matters

The core business problem is not merely searching code. Developers often need the reason behind the code: why a design exists, why a workaround was chosen, why a constraint was accepted, and why an old approach was abandoned. Source code alone usually answers what and how. Git history answers when, who, and what changed. Jira explains the tracked bug/task/release. Confluence explains why.

| **Source**     | **Primary question it answers**      | **Example**                                     |
|----------------|--------------------------------------|-------------------------------------------------|
| Source code    | What / How                           | What does ObjectManager::Release currently do?  |
| Git history    | When / Who / What changed            | Which commit changed the release logic?         |
| Jira           | Problem / Requirement / Status       | Which bug or release required this fix?         |
| Confluence     | Why / Decision / Context / Trade-off | Why did the team choose this locking strategy?  |
| Media/diagrams | Flow / visual context                | What is the intended architecture or user flow? |

Therefore Confluence is a first-class knowledge source, not a secondary document dump. If Confluence is skipped or weakly processed, the platform becomes only a better code search tool. If Confluence is processed with page hierarchy, relationships, media, and decision context, the platform can answer design and reasoning questions more reliably.

# 6. GitAI Reference: What to Learn and What Not to Copy

The reference GitAI-Chatbot project is valuable as an architectural pattern, especially its Clean/Hexagonal Architecture, OrchestratorService, RagService, VerifyService, RepoService, and GitHub/Gerrit adapters. However, based on the supplied analysis, it mostly ingests commit metadata and does not ingest source code, AST, diffs, call graph, or function/class definitions. That makes it a Commit Intelligence system, not a Code Intelligence or Organization Knowledge Platform.

| **Capability**                      | **GitAI-style metadata system** | **This platform**                  |
|-------------------------------------|---------------------------------|------------------------------------|
| Commit/PR search                    | Yes                             | Yes                                |
| GitHub/Gerrit adapters              | Yes                             | Yes, reusable idea                 |
| Confluence reasoning context        | No                              | Yes, first-class                   |
| Jira issue graph                    | Limited/No                      | Yes, target                        |
| Source code ingestion               | No                              | Yes                                |
| Minimal symbol index                | No                              | Yes, MVP                           |
| Tree-sitter/AST                     | No                              | Phase 1.5/2 depending on resources |
| Code Q&A Level B                    | No                              | Yes, target                        |
| Root cause / introduce-bug analysis | No                              | Future phase                       |

# 7. Architecture Overview

The core architecture principle is source-specific ingestion and source-agnostic normalization. Connectors handle source-specific APIs, rate limits, pagination, authentication, and raw data. Processors then convert data into common platform models. Downstream retrieval and agents should consume normalized records rather than raw Confluence or GitHub-specific shapes.

![](media/image2.png)

Figure 2. Part 1 POC Flow

| **Layer**           | **Purpose**                                          | **Part 1 responsibility**      |
|---------------------|------------------------------------------------------|--------------------------------|
| Source layer        | Connect to Confluence, Git/Gerrit, Jira, media, code | Yes                            |
| Raw layer           | Store original data for audit and reprocessing       | Yes                            |
| Normalization layer | Convert to CanonicalDocument and related models      | Yes                            |
| Processing layer    | Chunking, relation extraction, ACL, minimal symbols  | Yes                            |
| Export layer        | JSONL handoff to Task 2                              | Yes                            |
| Retrieval layer     | Embedding, Qdrant, ranking                           | No, but schema must support it |
| Agent layer         | RAG, Q&A, report, MCP                                | No                             |

# 8. Part 1 Module Structure

The following repository structure is only for Part 1. It is intentionally smaller than the whole platform structure. It should be enough for a team starting from zero and implementing modules independently as long as the shared domain models and output contract are agreed first.

```
part1-knowledge-foundation/
├── config/
│ ├── confluence_scope.yaml
│ ├── source_config.yaml
│ ├── sync_config.yaml
│ └── path_config.yaml
├── domain/
│ ├── models/
│ │ ├── source.py
│ │ ├── raw_document.py
│ │ ├── canonical_document.py
│ │ ├── chunk_record.py
│ │ ├── relation_record.py
│ │ ├── acl_record.py
│ │ ├── media_asset.py
│ │ ├── symbol_record.py
│ │ ├── sync_state.py
│ │ └── quality_report.py
│ └── ports/
│ ├── source_connector.py
│ ├── raw_store.py
│ ├── metadata_store.py
│ ├── file_store.py
│ └── exporter.py
├── connectors/
│ ├── confluence/
│ ├── git/
│ ├── gerrit/
│ └── jira_stub/
├── processors/
│ ├── scope_filter/
│ ├── normalizer/
│ ├── html_to_markdown/
│ ├── chunker/
│ ├── relation_extractor/
│ ├── acl_extractor/
│ ├── media/
│ └── symbol_indexer/
├── stores/
│ ├── local_raw_store.py
│ ├── local_file_store.py
│ └── sqlite_metadata_store.py
├── exporters/
│ ├── jsonl_exporter.py
│ ├── qdrant_payload_exporter.py
│ └── manifest_exporter.py
├── jobs/
│ ├── confluence_inventory_job.py
│ ├── confluence_full_sync_job.py
│ ├── git_scan_job.py
│ ├── build_chunks_job.py
│ └── export_dataset_job.py
├── cli/
│ ├── sync_confluence.py
│ ├── scan_git.py
│ ├── build_dataset.py
│ └── generate_quality_report.py
└── tests/
```

| **Module**                    | **MVP responsibility**                                   | **Output**                              |
|-------------------------------|----------------------------------------------------------|-----------------------------------------|
| config                        | Store source, scope, paths, rate limit, Jira key pattern | Config objects                          |
| domain/models                 | Stable schema shared by all modules                      | Typed records                           |
| connectors/confluence         | Inventory and crawl pages/attachments                    | RawDocument, MediaAsset, SyncState      |
| connectors/git                | Scan spensdk and git metadata                            | Code documents, SymbolRecord candidates |
| processors/scope_filter       | Include/exclude by page tree and relevance               | Scope decisions                         |
| processors/chunker            | Generate text/code chunks                                | ChunkRecord                             |
| processors/relation_extractor | Extract Jira keys, links, file paths, symbols            | RelationRecord                          |
| processors/media              | Metadata-first media extraction                          | MediaAsset/MediaDocument                |
| exporters                     | Write JSONL output contract                              | JSONL + manifest + report               |

# 9. Confluence Scope Filtering Strategy

Confluence filtering must not depend only on include_keywords. Keyword filtering is useful but it can miss important pages with unclear titles. The primary scope mechanism should be deterministic page-tree filtering using include_roots and exclude_subtrees by page ID.

![](media/image3.png)

Figure 3. Confluence Scope Filtering

```
confluence:
source_id: confluence_svmc_poc
space_key: SVMC
include_roots:
- page_id: "938880621"
name: "SVMC root folder for POC"
exclude_subtrees:
# Fill manually after inventory review.
# Examples: team building, travel, birthday, photo albums.
- page_id: "<exclude_page_id>"
reason: "non-work / media-heavy page"
relevance_keywords:
include_hint:
- architecture
- design
- flow
- spec
- guide
- issue
- bug
- crash
- ANR
- OOM
- sync
- render
- object
- API
exclude_hint:
- team building
- trip
- travel
- birthday
- dinner
- photo album
- outing
attachment_policy:
crawl_metadata: true
download_media_only_if_parent_relevant: true
process_video: false
```

The crawler should first build an inventory report, not immediately deep-crawl every page and attachment. The inventory should allow manual review and precise subtree exclusion before expensive media download or OCR.

| **Decision**                         | **Reason**                                                                        |
|--------------------------------------|-----------------------------------------------------------------------------------|
| Use include_roots by page ID         | Deterministic and less likely to miss important pages than keyword-only filtering |
| Use exclude_subtrees by page ID      | Efficiently removes team event/photo/travel branches                              |
| Use keywords as hints                | Good for relevance scoring, not for hard inclusion                                |
| Generate inventory report first      | Enables manual review of suspicious pages before expensive processing             |
| Do not download all media by default | Prevents cost/time explosion from non-work pages                                  |

# 10. Confluence Connector MVP

The Confluence connector must support the current API limitation and internal environment constraints. It should use the personal PAT for POC and store raw data locally. It must be resumable and rate-limit aware because even a small full crawl can take hours under 20 requests/minute.

| **Feature**    | **MVP requirement**                                                                     |
|----------------|-----------------------------------------------------------------------------------------|
| Authentication | Bearer PAT from local config or environment variable                                    |
| Scope          | SVMC / parent page id 938880621 for POC                                                 |
| Inventory      | Fetch descendants, title, id, parent, ancestors/path, labels if available, updated time |
| Content        | Fetch body storage/view and convert to clean Markdown/text                              |
| Attachments    | Fetch attachment metadata; defer download until page is relevant                        |
| ACL            | Fetch or preserve restriction metadata when available                                   |
| Rate limit     | Configurable 20/100 requests per minute with retry-after handling                       |
| Sync state     | Checkpoint per page and per attachment                                                  |
| Output         | Raw JSON + CanonicalDocument + ChunkRecord + MediaAsset + ACLRecord                     |

```
# CQL direction for inventory
space="SVMC" and ancestor=938880621 and type=page
# Exclude strategy
space="SVMC" and ancestor=938880621 and type=page and ancestor not in (<excluded_subtree_ids>)
```

# 11. Media and Attachment Ingestion Strategy

Media must be treated as a controlled ingestion stream, not as a universal vision task. The correct strategy is metadata-first, parse-before-vision, OCR-before-vision, and video-deferred unless a cheap extraction path is identified.

![](media/image4.png)

Figure 4. Media Ingestion Policy

| **Media type**     | **MVP action**                                                                               | **Reason**                                          |
|--------------------|----------------------------------------------------------------------------------------------|-----------------------------------------------------|
| draw.io / .io      | Download if parent page is relevant; parse XML/mxGraph where possible                        | More accurate and cheaper than vision               |
| PDF                | Download if parent page is relevant; extract text and metadata                               | Often contains design/spec content                  |
| Image / screenshot | Download only if relevant; OCR first; vision optional for selected important images          | Avoid high cost and hallucination                   |
| Video              | Metadata only in MVP; content analysis deferred unless cheap keyframe/transcript path exists | Likely demo-only and expensive to process           |
| Non-work media     | Skip download and processing                                                                 | Team trip/photo pages are high-volume and low-value |

MediaAsset schema example:

```
{
"media_id": "confluence:attachment:123456",
"parent_document_id": "confluence:page:938880621",
"source_system": "confluence",
"filename": "object_release_flow.drawio",
"mime_type": "application/xml",
"size_bytes": 124000,
"download_status": "downloaded | metadata_only | skipped",
"processing_status": "parsed | ocr_done | deferred | failed",
"relevance": "high | medium | low | non_work",
"extracted_text": "...",
"summary": "...",
"confidence": 0.82
}
```

# 12. Git / spensdk Connector and Minimal Symbol Index

The POC repository is spensdk. Since the repo is large, the POC should prefer local clone scanning for source files and lightweight git metadata. Heavy binary/generated/build directories must be excluded. The MVP needs a minimal symbol index because the product target includes code Q&A Level B and possibly Level C.

| **Item**     | **MVP approach**                                                              |
|--------------|-------------------------------------------------------------------------------|
| Repo         | spensdk                                                                       |
| Access       | Prefer local clone for POC; GitHub/Gerrit API can be added later              |
| Languages    | C++, Java, Kotlin, XML initially                                              |
| Exclude      | build outputs, binaries, generated files, vendor libs, .so/.dll, large assets |
| Git metadata | Commit hash, author, date, message, touched files, branch if available        |
| Jira keys    | Regex extraction from commit messages and PR/change metadata when available   |
| Symbol index | Minimal function/class/method/package/file index; no full call graph in MVP   |

SymbolRecord example:

```
{
"symbol_id": "spensdk:develop:src/native/ObjectManager.cpp:ObjectManager::Release",
"repo": "spensdk",
"branch": "develop",
"file_path": "src/native/ObjectManager.cpp",
"language": "cpp",
"symbol_type": "method",
"name": "Release",
"qualified_name": "ObjectManager::Release",
"signature": "void ObjectManager::Release(Object* obj)",
"line_start": 120,
"line_end": 180,
"parent_symbol": "ObjectManager",
"chunk_id": "chunk:..."
}
```

Tree-sitter is recommended if available, but the POC can start with simpler language-aware parsing. The important part is to create a stable symbol schema now so downstream retrieval can filter by symbol, file, language, and repo.

# 13. Jira Key Extraction Without Jira PAT

Jira PAT is not required for the first POC. The system can extract Jira keys from Confluence pages, Git commit messages, file names, PR/change metadata, and comments using a configurable regex. Later, when Jira PAT is available, the same keys can be hydrated into full Jira issue records.

```
jira:
enabled: false
extraction_mode: regex_only
key_patterns:
- "[A-Z][A-Z0-9]+-[0-9]+"
allowed_project_keys:
- SPEN
- NOTES
- SDK
```

| **Phase**       | **Jira behavior**                                                                                   |
|-----------------|-----------------------------------------------------------------------------------------------------|
| POC without PAT | Extract Jira keys only; create RelationRecord with status unresolved_without_jira_api               |
| After PAT       | Fetch Bug/Task/Story/Epic/Sprint/Release/Comment/Attachment metadata and hydrate existing relations |
| Long-term       | Use Jira as a first-class source for issue-to-code-to-wiki traceability                             |

RelationRecord example without Jira API:

```
{
"relation_id": "rel:confluence:page:123:mentions:SPEN-1234",
"source_id": "confluence:page:123",
"target_id": "jira:issue:SPEN-1234",
"relation_type": "mentions_jira_key",
"confidence": 0.95,
"resolution_status": "unresolved_without_jira_api"
}
```

# 14. ACL and Security Model

The POC will use the owner personal PAT. This means the crawler can only access data visible to that user. This is acceptable for POC, but the data model must record permission metadata from the beginning. Otherwise it will be difficult and risky to retrofit ACL later.

| **Topic**             | **MVP decision**                                                                                      |
|-----------------------|-------------------------------------------------------------------------------------------------------|
| Crawler identity      | Personal PAT for POC                                                                                  |
| Future identity       | Service account or managed crawler account                                                            |
| ACL storage           | Store restricted/unrestricted flag, visible users/groups when available, and crawler identity         |
| Retrieval implication | Task 2/3 must filter results by permission before answering in multi-user mode                        |
| Security risk         | Never assume Qdrant alone enforces permissions; ACL must be represented in payload and metadata store |

ACLRecord example:

```
{
"document_id": "confluence:page:123",
"source_system": "confluence",
"crawler_identity": "personal_pat:<owner>",
"is_restricted": true,
"allowed_users": ["user1"],
"allowed_groups": ["notes-core"],
"acl_extraction_status": "partial | complete | unavailable"
}
```

# 15. Storage Strategy

The POC should use local storage, but it must be designed behind interfaces so the system can move to an internal server later. Raw data must be preserved to allow reprocessing when chunking, prompt templates, OCR, or extraction logic changes.

![](media/image5.png)

Figure 6. Storage Model: POC Now, Server Later

```
data/
├── raw/
│ ├── confluence/pages/
│ ├── confluence/attachments/
│ └── git/
├── normalized/
│ ├── documents.jsonl
│ ├── media_assets.jsonl
│ └── symbols.jsonl
├── chunks/
│ └── chunks.jsonl
├── relations/
│ └── relations.jsonl
├── acl/
│ └── acl.jsonl
├── sync/
│ └── sync_state.jsonl
└── reports/
├── inventory_report.csv
└── quality_report.md
```

# 16. Output Contract to Task 2 and Task 3

Part 1 must provide a stable output contract. This is the most important agreement between teams that implement independently. Task 2 should be able to embed and index chunks without understanding the Confluence API, Git internals, or local raw file layout.

![](media/image6.png)

Figure 5. Part 1 Output Contract to Other Teams

| **File**           | **Purpose**                                                       | **Required in POC?** |
|--------------------|-------------------------------------------------------------------|----------------------|
| documents.jsonl    | Normalized source documents from Confluence, Git/code, later Jira | Yes                  |
| chunks.jsonl       | Text/code/media chunks for embedding and Qdrant payload           | Yes                  |
| relations.jsonl    | Links between Wiki, Jira keys, Git, files, symbols, media         | Yes                  |
| acl.jsonl          | Permission/restriction metadata                                   | Yes                  |
| media_assets.jsonl | Attachment/media metadata and extraction results                  | Yes                  |
| symbols.jsonl      | Minimal code symbol index for spensdk                             | Yes                  |
| sync_state.jsonl   | Checkpoint, crawl status, hashes, errors                          | Yes                  |
| manifest.json      | Dataset version, counts, config hash, generated time              | Yes                  |
| quality_report.md  | Human-readable issues, skipped data, coverage, warnings           | Yes                  |

ChunkRecord example:

```
{
"chunk_id": "chunk:confluence:page:123:section:2",
"document_id": "confluence:page:123",
"source_system": "confluence",
"source_type": "wiki_page",
"title": "ObjectManager Design Note",
"text": "...chunk text...",
"language": "en | ko | vi | code | mixed",
"space_key": "SVMC",
"repo": null,
"file_path": null,
"symbol": null,
"jira_keys": ["SPEN-1234"],
"relation_ids": ["rel:..."],
"acl_tags": ["group:notes-core"],
"updated_at": "2026-07-01T00:00:00Z"
}
```

# 17. Qdrant Integration Contract

Knowledge Sources can be combined with Qdrant by normalizing all sources into common ChunkRecord payloads. Qdrant should store vectors plus payload; it should not be the only source of truth. Raw Store, Metadata Store, Relation Store, and ACL data remain necessary.

| **Qdrant payload field**  | **Reason**                                                    |
|---------------------------|---------------------------------------------------------------|
| source_system             | Filter by confluence, git, gerrit, jira, code                 |
| source_type               | Distinguish wiki_page, code_symbol, commit, media, jira_issue |
| document_id / chunk_id    | Stable lookup and traceability                                |
| space_key / page_id       | Confluence filtering and source display                       |
| repo / branch / file_path | Code and Git filtering                                        |
| symbol / language         | Code Q&A retrieval                                            |
| jira_keys                 | Issue traceability                                            |
| relation_ids              | Context expansion across sources                              |
| acl_tags                  | Permission filtering                                          |
| updated_at / version      | Freshness and incremental sync                                |

A typical code question should retrieve code chunks, then expand to related Confluence pages and Jira keys using RelationRecord. A typical design question should retrieve Confluence chunks, then expand to code files, symbols, commits, and Jira keys.

# 18. Sync, Rate Limit, and Resumability

The Confluence API may be limited to 20 requests/minute, while a higher limit such as 100 requests/minute may be possible by request. The project should request 100 requests/minute for initial indexing, but the crawler must remain correct at 20 requests/minute.

| **Scenario**                      | **20 req/min rough impact** | **100 req/min rough impact** | **Design action**                    |
|-----------------------------------|-----------------------------|------------------------------|--------------------------------------|
| 6,000 page content requests       | About 5 hours               | About 1 hour                 | Acceptable if resumable              |
| 20,000–30,000 multi-step requests | About 16–25 hours           | About 3–5 hours              | Need checkpoint and incremental sync |
| Attachment/media processing       | Potentially much higher     | Still costly                 | Filter relevance before download     |

```
sync:
rate_limit_per_minute: 20 # default safe mode
requested_initial_limit: 100 # if approved for full sync
retry:
max_attempts: 5
respect_retry_after: true
exponential_backoff: true
checkpoint:
enabled: true
granularity: page_and_attachment
incremental:
use_updated_time: true
use_content_hash: true
```

# 19. POC Build Order and Acceptance Criteria

The POC should prove one end-to-end path before attempting all 6,000 pages or all repositories. Do not build the chatbot first. Do not push raw data directly into Qdrant. Do not deep-process all media first.

1.  Create domain models and JSONL output schema.

2.  Create Confluence scope config for SVMC / 938880621.

3.  Build inventory job: include root, exclude subtree, report page counts and attachment counts.

4.  Build Confluence page crawler with raw store, checkpoint, and rate limiter.

5.  Normalize selected pages into CanonicalDocument.

6.  Extract Jira keys by regex and create RelationRecord.

7.  Create attachment metadata inventory and process selected draw.io/PDF/image only for relevant pages.

8.  Scan spensdk local repo and generate minimal SymbolRecord.

9.  Chunk documents and code into ChunkRecord.

10. Export JSONL files, manifest, and quality report.

| **Acceptance criterion** | **Definition**                                                     |
|--------------------------|--------------------------------------------------------------------|
| Scope control            | Crawler can include SVMC/938880621 and exclude configured subtrees |
| Resumability             | Interrupted crawl can continue without starting over               |
| Raw preservation         | Every processed page has raw JSON stored locally                   |
| Normalization            | Every processed page maps to CanonicalDocument                     |
| Chunking                 | Chunks include stable IDs and payload metadata                     |
| Jira regex               | Jira-like keys are extracted with allowed project filtering        |
| Media policy             | Non-relevant pages do not download/process media                   |
| Symbol index             | spensdk source files produce minimal SymbolRecord output           |
| Output contract          | All required JSONL files and manifest are generated                |
| Quality report           | Report contains counts, skips, failures, and coverage warnings     |

# 20. Risks, Non-Goals, and Open Questions

## 20.1 Main Risks

| **Risk**                                   | **Mitigation**                                                              |
|--------------------------------------------|-----------------------------------------------------------------------------|
| Over-crawling non-work Confluence pages    | Use page ID scope, exclude_subtrees, inventory report before media download |
| API rate limit causing long/failing crawls | Checkpoint, retry, rate limiter, request 100 req/min for initial sync       |
| ACL leakage later                          | Capture permission metadata from the beginning                              |
| Media cost explosion                       | Metadata-first, parse/OCR before vision, video deferred                     |
| AI-generated docs become unverified        | Quality report and source provenance for every chunk                        |
| Team modules incompatible                  | Freeze domain models and output contract first                              |

## 20.2 Explicit Non-Goals for POC

- No production chatbot UI.

- No final RAG answer generation.

- No full video understanding.

- No complete call graph or root cause analysis.

- No full Jira ingestion until Jira PAT is available.

- No assumption that Qdrant is the only database.

## 20.3 Open Questions

- Which exact Confluence subtrees under SVMC/938880621 should be excluded in the first POC?

- Which branch of spensdk should be scanned first: develop, release branch, or both?

- Should minimal symbol extraction use Tree-sitter immediately or start with simpler language-aware parsing?

- What are the official allowed Jira project keys for regex extraction?

- Where will POC raw data be stored on the local machine, and what is the maximum allowed disk usage?

- Who will own Task 2 output validation once chunks.jsonl is ready?

# Appendix A. Minimal Canonical Models

CanonicalDocument:

```
{
"document_id": "confluence:page:123",
"source_system": "confluence",
"source_type": "wiki_page | code_file | commit | media | jira_stub",
"title": "...",
"body_text": "...",
"raw_uri": "data/raw/...",
"parent_ids": ["..."],
"labels": ["..."],
"updated_at": "...",
"author": "...",
"acl_id": "acl:...",
"metadata": {}
}
```
RelationRecord:

```
{
"relation_id": "rel:...",
"source_id": "...",
"target_id": "...",
"relation_type": "mentions_jira_key | links_to_page | references_file | defines_symbol | belongs_to_parent",
"evidence": "...",
"confidence": 0.0
}
```

# Appendix B. Practical Prompt for Claude Code Later

When implementation starts, do not ask Claude Code to build the whole platform. Use this spec as master context, then assign one bounded module at a time. Example:

```
Read AI_Knowledge_Platform_Master_Spec_v7.docx and implement only the Confluence Inventory MVP.
Scope:
- Load config/confluence_scope.yaml
- Use PAT from environment variable
- Fetch descendants under space SVMC and parent page id 938880621
- Support exclude_subtrees by page id
- Output inventory_report.csv and pages_inventory.jsonl
- Do not download attachments yet
- Add rate limiter and checkpoint
- Add tests with mocked Confluence responses
Out of scope:
- Qdrant
- RAG
- final chatbot
- full media processing
```
