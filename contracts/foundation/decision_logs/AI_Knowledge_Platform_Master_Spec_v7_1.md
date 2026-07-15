**AI Knowledge Platform  
Master Specification v7.1**

*Organization Knowledge Platform for Confluence, Git/Gerrit, Jira, Source Code, Media, and Future MCP*

| **Field**                      | **Value**                                                       |
|--------------------------------|-----------------------------------------------------------------|
| Version | v7.1 |
| v7.1 change basis | External spec review 2026-07-02 — P0 gaps only; spec update, no code |
| Authoritative format (v7.1) | This Markdown file, plus CHUNKING_SPEC.md and schemas/ |
| Decision log (v7.2) | AI_Knowledge_Platform_v7_2_Update.md layers Part 2 / storage / integration decisions on this spec |
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

# Change Log v7 → v7.1

v7.1 is a **specification update only**. It resolves the P0 gaps identified in the 2026-07-02 review. The v7 vision, POC scope (SVMC/938880621 + spensdk), ownership boundaries, and non-goals are unchanged. No Task 2/Task 3 design, no chatbot/RAG/MCP content, no implementation.

| # | Review item | Change | Where |
|---|---|---|---|
| 1 | Faithful Markdown | Document regenerated from the DOCX; content-equivalent. For v7.1 this Markdown is the authoritative version. | Whole document |
| 2 | Normative schemas | All output-contract examples converted to JSON Schema 2020-12 in `schemas/`; every record carries `schema_version`; exporters must validate before writing. | §16.1, Appendix A, `schemas/` |
| 3 | Chunking spec | Wiki/code chunk units, token caps, overlap, stable `chunk_id`, and update behavior fully specified. | §16.3, `CHUNKING_SPEC.md` |
| 4 | Macro policy | Storage-format macro handling defined for code, drawio, include/excerpt, expand, jira, toc, admonitions, and unknown macros. | §10.1 |
| 5 | Delete/version semantics | Confluence `version.number` captured as `source_version`; tombstone records added to the contract; `full_snapshot`/`delta` export modes defined. | §10.1, §16.2, §18.1–18.3 |
| 6 | ACL rules | `acl_tags` grammar, default-deny materialization, deny-safe restriction-inheritance intersection, group/user resolution boundary, POC exposure rule. | §14.1–14.4 |
| 7 | Symbol versioning & parser | `commit_hash` and `parse_status` added to SymbolRecord; MVP parser decided: tree-sitter for C++ and Java; Kotlin/XML symbols deferred. | §12.1, §12.2 |
| 8 | Exporter dedup | `qdrant_payload_exporter` removed; `chunks.jsonl` is the single payload contract. | §8, §17 |
| — | Schema unification | RelationRecord unified into one shape (incl. `resolution_status`); `acl_id` added to ACLRecord; deterministic `relation_id`. | §13, §14, `schemas/` |

Content added or changed in v7.1 is marked *(v7.1)*. Unmarked content is unchanged from v7.

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
| Normative contract *(v7.1)* | JSON Schemas in schemas/ are authoritative; tombstone records propagate deletions |
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

*(v7.1)* The former `exporters/qdrant_payload_exporter.py` is removed from the module tree: `chunks.jsonl` is the single embedding/payload contract (see §17).

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

## 10.1 Storage-Format Macro Handling Policy *(v7.1)*

Confluence `body.storage` is XHTML containing `<ac:structured-macro>` elements. The normalizer must apply the per-macro policy below when converting to Markdown. Two rules are normative for **all** macros:

- **M-1 (no silent loss).** Text content inside any macro body must never be silently discarded. If a macro is not recognized, its `ac:rich-text-body` text is inlined and the macro is counted as unhandled.
- **M-2 (counted).** The quality report must include per-macro counters: `macros_handled{name}`, `macros_unhandled{name}`, `toc_dropped`.

| Macro (`ac:name`) | MVP handling | Markdown output | Side records |
|---|---|---|---|
| `code` | Extract `language` and `title` parameters and the CDATA body. | Fenced code block with language tag; `title` as a preceding bold line. | — |
| `drawio` | Do not render; resolve the referenced attachment by diagram name. | Placeholder `[diagram: {name}]`. | MediaAsset link; RelationRecord `embeds_media` (`resolution_status: unresolved_target` if the attachment cannot be matched). |
| `include`, `excerpt-include` | Do not fetch cross-page content in MVP. | Placeholder `[included from page: {title-or-id}]`. | RelationRecord `includes_page`, `resolution_status: deferred_mvp`. |
| `excerpt` (defined on the page itself) | Body is local content. | Inline the body normally. | — |
| `expand` | Body is present in storage format and must not be lost. | `title` parameter as a bold line, body inlined. | — |
| `jira` | Extract the issue key(s) from macro parameters. | Plain key text, e.g. `SPEN-1234`. | RelationRecord `mentions_jira_key`, `evidence: "jira_macro"`, confidence 0.99 (higher than plain regex). |
| `toc` | Derivable from headings; drop. | Nothing. | Counted as `toc_dropped`. |
| `info`, `note`, `warning`, `tip`, `panel` | Common admonitions; keep body. | Blockquote with a bold prefix, e.g. `> **Note:** ...`. | — |
| Image / attachment refs (`ac:image` + `ri:attachment`) | Same policy family as §11. | Placeholder `[media: {filename}]`. | MediaAsset per §11; RelationRecord `embeds_media`. |
| Unknown / other | Apply M-1. | Inline the `ac:rich-text-body` text prefixed with `[macro:{name}]`; if there is no rich-text body, emit `[macro:{name} omitted]`. | Counter `macros_unhandled{name}` incremented. |

*(v7.1)* The content fetch must additionally capture the Confluence page version: `version.number` is stored as `CanonicalDocument.source_version` and `version.when` as `updated_at`. See §18.1.

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

MediaAsset example (normative shape in `schemas/media_asset.schema.json`; *(v7.1)* enum fields now hold a single value instead of the v7 pipe-separated option list):

```json
{
  "schema_version": "1.0",
  "media_id": "confluence:attachment:123456",
  "parent_document_id": "confluence:page:938880621",
  "source_system": "confluence",
  "filename": "object_release_flow.drawio",
  "mime_type": "application/xml",
  "size_bytes": 124000,
  "download_status": "downloaded",
  "processing_status": "parsed",
  "relevance": "high",
  "extracted_text": "...",
  "summary": "...",
  "confidence": 0.82,
  "raw_uri": "data/raw/confluence/attachments/123456",
  "content_hash": null,
  "source_version": "3",
  "updated_at": "2026-07-01T00:00:00Z",
  "crawled_at": "2026-07-02T00:00:00Z"
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

## 12.1 Parser Decision and Definition of "Minimal" *(v7.1)*

**Decision: the MVP symbol indexer uses tree-sitter (py-tree-sitter) with the official `tree-sitter-cpp` and `tree-sitter-java` grammars.** Regex or ad-hoc parsing of C++ is explicitly rejected: templates, preprocessor macros, and namespaces make non-grammar extraction unreliable. Kotlin symbol extraction is deferred to Phase 1.5 (`tree-sitter-kotlin` exists but is lower priority). XML files produce no SymbolRecords in MVP — they are still ingested as code documents and chunked by the fallback window rule in `CHUNKING_SPEC.md`.

Scope of "minimal" (normative):

| Extracted in MVP | Not extracted in MVP |
|---|---|
| `class`, `struct`, `interface`, `enum`, `function`, `method`, `namespace`/`package` declarations with line ranges | Fields/variables, references, call edges/call graph |
| Qualified name, signature string, parent symbol | Overload resolution beyond the signature string |
| Leading doc-comment block, attached to the symbol's chunk | Template instantiations, preprocessor-expanded variants |

C++ files are parsed as-is without preprocessing; files with heavy conditional/macro code may produce tree-sitter ERROR nodes. Such files are recorded with `parse_status: "partial"` and counted in the quality report; extraction must not abort the scan.

## 12.2 Symbol Versioning *(v7.1)*

Every SymbolRecord carries the full `commit_hash` of the scanned working tree; `line_start`/`line_end` are valid only at that commit. `symbol_id` keeps the v7 format `{repo}:{branch}:{file_path}:{qualified_name}` and is treated as an opaque identifier. When two symbols in one file share a qualified name (overloads), the suffix `~{sha256(signature)[:8]}` is appended. The POC scans exactly one configured branch (§20.3).

SymbolRecord example (normative shape in `schemas/symbol_record.schema.json`):

```json
{
  "schema_version": "1.0",
  "symbol_id": "spensdk:develop:src/native/ObjectManager.cpp:ObjectManager::Release",
  "repo": "spensdk",
  "branch": "develop",
  "commit_hash": "3f9c1a7d0b2e4c6f8a1b3d5e7f9a0c2e4b6d8f0a",
  "file_path": "src/native/ObjectManager.cpp",
  "language": "cpp",
  "symbol_type": "method",
  "name": "Release",
  "qualified_name": "ObjectManager::Release",
  "signature": "void ObjectManager::Release(Object* obj)",
  "line_start": 120,
  "line_end": 180,
  "parent_symbol": "ObjectManager",
  "chunk_id": "chunk:git:9a1b3d5e7f9a0c2e",
  "parse_status": "ok",
  "scanned_at": "2026-07-02T00:00:00Z"
}
```

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

RelationRecord example without Jira API. *(v7.1)* RelationRecord is unified into a single normative shape (`schemas/relation_record.schema.json`) that includes `resolution_status` and `created_at`, replacing the divergent Appendix A variant. `relation_id` is deterministic: `"rel:" + sha256(source_id + "\x1f" + relation_type + "\x1f" + target_id)[:16]`, which deduplicates repeated extractions for free.

```json
{
  "schema_version": "1.0",
  "relation_id": "rel:5f2a9c1e7b3d8a04",
  "source_id": "confluence:page:123",
  "target_id": "jira:issue:SPEN-1234",
  "relation_type": "mentions_jira_key",
  "evidence": "regex:page_body",
  "confidence": 0.95,
  "resolution_status": "unresolved_without_jira_api",
  "created_at": "2026-07-02T00:00:00Z"
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

## 14.1 acl_tags Grammar *(v7.1)*

`acl_tags` is the single permission representation carried by chunks and consumed by downstream filtering. Tags use **OR semantics**: a caller identity matching any tag may see the record.

```
acl_tag   := "user:" principal
           | "group:" principal
           | "space:" SPACE_KEY
           | "repo:" repo_name
           | "restricted:unresolved"
principal := Confluence user key or group key, lowercased, no whitespace
repo_name := Git repository name, lowercased, no whitespace
```

- An unrestricted page carries exactly `["space:{SPACE_KEY}"]`, meaning "every user with view permission on the space". Part 1 does not enumerate space members.
- *(v7.2)* A git-source chunk carries exactly `["repo:{repo}"]` (POC: `repo:spensdk`), meaning "every user with read access to the repository" — the git analogue of `space:`. Part 1 does not enumerate repo members; caller → repo-read resolution belongs to the query-time resolver (14.4).
- A view-restricted page carries only the explicit principals, e.g. `["group:notes-core", "user:alice"]`. The `space:` tag is removed because restrictions narrow visibility.
- `restricted:unresolved` matches no caller identity and therefore hides the record (see 14.3).

## 14.2 Restriction Inheritance — Deny-Safe Intersection *(v7.1)*

Confluence semantics: a viewer must satisfy the view restriction at **every** restricted ancestor level; effective visibility is an intersection. Flat OR-semantics tags cannot express an intersection exactly, so the ACL extractor computes a deny-safe approximation:

1. Collect the view-restriction principal sets along the ancestor chain, including the page itself. Zero restricted levels → `["space:{SPACE_KEY}"]`.
2. Exactly one restricted level → that level's principals.
3. Multiple restricted levels → users present in **every** level's user list, plus groups present in **every** level's group list. Part 1 never expands group membership, so groups that differ across levels cannot be intersected and are dropped.
4. If the result is empty → `["restricted:unresolved"]`.
5. Whenever rule 3 dropped any principal, set `acl_confidence: "approximate"` and list the document in the quality report for manual review.

**Normative invariant: any approximation must err toward more restrictive.** It may hide a document from a legitimate viewer; it must never expose a document to a non-viewer.

Worked example: an ancestor is restricted to `group:notes-core`; the page itself is additionally restricted to `user:alice`. No principal appears at both levels, so the effective tags are `["restricted:unresolved"]` with `acl_confidence: "approximate"` — hidden until manually reviewed.

## 14.3 Default Deny *(v7.1)*

If `acl_extraction_status` is `unavailable` (the API returned no restriction data) or extraction failed, the document and all of its chunks carry `acl_tags: ["restricted:unresolved"]`. Records are never emitted with an empty `acl_tags` array — the schemas enforce `minItems: 1`. The default is deny, not allow.

## 14.4 Group/User Resolution Boundary *(v7.1)*

Part 1 emits principal identifiers exactly as Confluence returns them and never expands group membership. Mapping group → members and caller identity → principals at query time is owned by the future platform permission resolver (Task 3 layer); the Part 1 contract is tags only. Because the POC dataset is crawled with a personal PAT, its visibility equals the PAT owner's visibility: **the POC dataset must not be served to any user other than the PAT owner.** Multi-user exposure requires a service-account crawl.

ACLRecord example (normative shape in `schemas/acl_record.schema.json`; *(v7.1)* adds `acl_id` — CanonicalDocument already referenced `acl_id` in v7, but ACLRecord itself was keyed only by `document_id`):

```json
{
  "schema_version": "1.0",
  "acl_id": "acl:confluence:page:123",
  "document_id": "confluence:page:123",
  "source_system": "confluence",
  "crawler_identity": "personal_pat:<owner>",
  "is_restricted": true,
  "restriction_inherited": true,
  "restriction_source_page_ids": ["938880621"],
  "allowed_users": ["alice"],
  "allowed_groups": ["notes-core"],
  "acl_tags": ["restricted:unresolved"],
  "acl_extraction_status": "partial",
  "acl_confidence": "approximate",
  "extracted_at": "2026-07-02T00:00:00Z"
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
├── tombstones/
│ └── tombstones.jsonl
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
| tombstones.jsonl *(v7.1)* | Deletion/invalidation records for previously exported entities (§16.2) | Yes, from the second sync run onward |
## 16.1 Normative Schemas *(v7.1)*

The JSON examples in this document are illustrative. **The normative definitions are the JSON Schema (draft 2020-12) files in `schemas/`** — one per output record type plus shared `defs.schema.json` (ID grammars, enums, timestamp format). Binding rules:

- Every record in every JSONL file carries `schema_version` (currently `"1.0"`).
- Exporters MUST validate each record against its schema before writing; a validation failure fails the export run.
- Unknown top-level fields are rejected (`additionalProperties: false`), except inside explicitly free-form `metadata` objects.
- Schema evolution: additive optional fields bump the minor version; breaking changes bump the major version and require a new `full_snapshot` export.

## 16.2 Export Modes, Delta Semantics, and Tombstones *(v7.1)*

`manifest.json` declares `export_mode`:

| Mode | Contents | Consumption rule for Task 2 |
|---|---|---|
| `full_snapshot` | Complete current state of all files. | May be applied as a full replacement of the index/stores. |
| `delta` | Only records added or changed since `base_dataset_version`, plus `tombstones.jsonl`. | MUST be applied as upsert-by-ID plus tombstone-driven deletes, in `dataset_version` order. |

A TombstoneRecord marks a previously exported entity as removed or invalidated:

```json
{
  "schema_version": "1.0",
  "tombstone_id": "tomb:1c4e8a2b6d0f3a75",
  "entity_type": "chunk",
  "entity_id": "chunk:confluence:0a1b2c3d4e5f6a7b",
  "reason": "content_updated",
  "detail": null,
  "detected_at": "2026-07-02T00:00:00Z",
  "dataset_version": "v20260702-153000",
  "source_version_last_seen": "17"
}
```

Reasons: `source_deleted`, `access_revoked`, `moved_out_of_scope`, `content_updated` (chunk superseded by re-chunking), `config_invalidated` (chunker or schema major-version change). Cascade rule: tombstoning a document tombstones its chunks, media assets, relations, and ACL record with the same reason. Detection mechanics: §18.2. **Purpose beyond hygiene:** tombstones are how deleted or access-revoked content gets purged from downstream vector stores — without them, restricted content persists in Qdrant indefinitely.

## 16.3 Chunking Specification *(v7.1)*

Chunking is fully specified in **`CHUNKING_SPEC.md`** (normative; versioned via `chunker_version`). Binding invariants, repeated here:

1. `chunk_id = "chunk:" + source_system + ":" + sha256(document_stable_key + US + unit_key + US + normalized_text)[:16]` where US is `\x1f`; a `-{n}` suffix is appended only for byte-identical duplicates. Branch and commit are provenance **fields**, never part of the ID — unchanged content keeps its ID across syncs so Task 2 can skip re-embedding.
2. Token budget is counted with the **selected embedding model's own tokenizer** — `all-MiniLM-L6-v2` (BERT WordPiece; 256-word-piece limit with silent truncation), **not** `tiktoken`: target 200, hard max 240 (≤ 256 minus the `[CLS]`/`[SEP]` tokens, so nothing is truncated), overlap 40, overlap applied only to forced splits of oversize units. These numbers are tuned to this model; a later embedding-model change bumps `chunker_version` and forces a `full_snapshot` (`config_invalidated`). Full detail in CHUNKING_SPEC.md §1.
3. Wiki unit = heading section (h1–h3) with a breadcrumb first line; code unit = one chunk per symbol with a path/symbol comment first line; fallback = token-packed line windows.
4. Update behavior = document-level hash short-circuit, then chunk-set diff: unchanged IDs are not re-emitted; disappeared IDs are tombstoned (`content_updated`).
5. Determinism: identical inputs and identical chunker config MUST produce a byte-identical chunk set.

ChunkRecord example (normative shape in `schemas/chunk_record.schema.json`):

```json
{
  "schema_version": "1.0",
  "chunk_id": "chunk:confluence:0a1b2c3d4e5f6a7b",
  "document_id": "confluence:page:123",
  "source_system": "confluence",
  "source_type": "wiki_page",
  "title": "ObjectManager Design Note",
  "text": "ObjectManager Design Note › Locking Strategy\n\n...chunk text...",
  "content_kind": "prose",
  "language": "en",
  "token_count": 205,
  "heading_path": ["ObjectManager Design Note", "Locking Strategy"],
  "space_key": "SVMC",
  "page_id": "123",
  "repo": null,
  "branch": null,
  "file_path": null,
  "symbol": null,
  "line_start": null,
  "line_end": null,
  "part_index": null,
  "part_total": null,
  "jira_keys": ["SPEN-1234"],
  "relation_ids": ["rel:5f2a9c1e7b3d8a04"],
  "acl_tags": ["space:SVMC"],
  "source_version": "17",
  "content_hash": "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00",
  "chunker_version": "1.1.0",
  "updated_at": "2026-07-01T00:00:00Z"
}
```

# 17. Qdrant Integration Contract

Knowledge Sources can be combined with Qdrant by normalizing all sources into common ChunkRecord payloads. Qdrant should store vectors plus payload; it should not be the only source of truth. Raw Store, Metadata Store, Relation Store, and ACL data remain necessary.

*(v7.1)* `qdrant_payload_exporter` (listed in the v7 §8 module tree) is removed. `chunks.jsonl` is the single payload contract: Task 2 derives the Qdrant payload directly from the ChunkRecord fields below — a second payload artifact would inevitably drift from it. Consumption of `acl_tags` follows §14; consumption of tombstones follows §16.2.

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

## 18.1 Version Capture *(v7.1)*

| Source | `source_version` on CanonicalDocument | Notes |
|---|---|---|
| Confluence page | `version.number` (as a string) | `version.when` becomes `updated_at`; both are fetched with the page content (§10.1). |
| Git code file | Full commit hash of the scanned tree | Same value as `SymbolRecord.commit_hash` for that scan. |
| Media asset | Attachment version if exposed, else the parent page version | Recorded on MediaAsset. |

`content_hash` (sha256 of the normalized body) is captured alongside. Incremental sync (config above) uses `updated_time` as the cheap change signal and `content_hash` as the authoritative change test.

## 18.2 Deletion Detection and Tombstones *(v7.1)*

On every sync run the crawler recomputes the in-scope inventory and diffs it against the previous inventory in the metadata store:

| Observation | Tombstone reason |
|---|---|
| Page absent from inventory; direct GET returns 404 | `source_deleted` (some Confluence versions return 404 for restricted pages too — record the ambiguity in `detail`) |
| Direct GET returns 403 | `access_revoked` |
| Page fetchable, but its ancestor chain is no longer under `include_roots`, or is now under `exclude_subtrees` | `moved_out_of_scope` |
| Re-chunking removed a chunk_id | `content_updated` |
| Chunker or schema major version changed | `config_invalidated` |

Cascade per §16.2. Tombstones are written to `tombstones.jsonl` of the export in which the removal was detected.

## 18.3 Update Propagation *(v7.1)*

Per changed document: (1) if `content_hash` and `chunker_version` are both unchanged → skip; emit nothing. (2) Otherwise re-chunk, diff the new chunk-ID set against the previous set, emit only new/changed chunks, and tombstone disappeared IDs (`content_updated`). ACL-only changes (restrictions changed, content identical) re-emit the ACLRecord and all affected ChunkRecords with updated `acl_tags` — same chunk IDs, no tombstones — unless visibility was lost entirely, which is `access_revoked` in §18.2.

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
| Schema validation *(v7.1)* | Every exported record validates against its schema in schemas/; a failing record fails the export run |
| Deletion propagation *(v7.1)* | Deleting a page or moving it out of scope produces correct tombstones on the next sync run |
| Macro coverage *(v7.1)* | code/drawio/include/expand/jira/toc handled per §10.1; unknown-macro text is never silently dropped; counters appear in the quality report |
| Chunk stability *(v7.1)* | Re-running the pipeline on unchanged input produces a byte-identical chunks.jsonl (§16.3 determinism) |
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

Resolved in v7.1: the symbol parser approach (tree-sitter for C++/Java — §12.1); and the chunk token budget, now tuned to the selected embedding model all-MiniLM-L6-v2 (§16.3, CHUNKING_SPEC §1).

Carried over from v7, still open:

- Which exact Confluence subtrees under SVMC/938880621 should be excluded in the first POC?
- Which branch of spensdk should be scanned first: develop, a release branch, or both? (The POC scans exactly one — §12.2.)
- What are the official allowed Jira project keys for regex extraction?
- Where will POC raw data be stored on the local machine, and what is the maximum allowed disk usage?
- Who will own Task 2 output validation once chunks.jsonl is ready?

New in v7.1:

- Token budget: **resolved** — the embedding model is all-MiniLM-L6-v2 (256-word-piece WordPiece, silent truncation). Budget is tuned to it: target 200 / hard max 240 / overlap 40, counted in the model's own tokenizer (§16.3, CHUNKING_SPEC §1). A later embedding-model change bumps `chunker_version` and forces a `full_snapshot`.
- Embedding-model fit (Task 2 concern, surfaced here): all-MiniLM-L6-v2 is English-only and was not trained on source code. If wiki content is substantially Korean/Vietnamese, or code retrieval quality is insufficient, Task 2 should evaluate a multilingual and/or code-aware model. This changes Task 2 config (and possibly `chunker_version`), not the Part 1 record shapes.
- Structure-aware retrieval readiness (forward-looking, Task 3 owns retrieval): Part 1 already preserves document hierarchy — the Confluence page tree (`include_roots`/ancestors), `heading_path` on every chunk, `parent_symbol` for code, and the relation graph including `includes_page`/`links_to_page`. This keeps future retrieval strategies open, including tree-navigation / "vectorless" approaches, without re-ingesting. An optional, additive `structure.jsonl` (node_id, parent_id, type, title, child chunk_ids) is noted as a possible post-MVP export. No retrieval logic is specified in Part 1.
- Is the deny-safe intersection approximation for multi-level restrictions (§14.2) acceptable to security review, or is exact evaluation required before any multi-user exposure?
- Should `include`/`excerpt-include` bodies be inlined post-MVP once cross-page fetch during normalization is cheap, or remain relation-only?
- `ChunkRecord.language` detection method is still unspecified; the MVP may emit `"unknown"`. Which detector, and per-chunk or per-document?
- Confirm Phase 1.5 timing for Kotlin symbol extraction.

# Appendix A. Minimal Canonical Models *(revised in v7.1)*

The v7 illustrative models formerly in this appendix are superseded by the normative JSON Schemas in `schemas/` (§16.1): `canonical_document`, `chunk_record`, `relation_record`, `acl_record`, `media_asset`, `symbol_record`, `sync_state_record`, `tombstone_record`, and `manifest`, plus shared `defs.schema.json` (ID grammars, enums, timestamp format).

Fields added in v7.1 relative to the v7 examples:

| Record | Added / changed in v7.1 |
|---|---|
| All records | `schema_version` (required) |
| CanonicalDocument | `source_version`, `content_hash`, `crawled_at`; `author` explicitly nullable |
| ChunkRecord | `content_kind`, `token_count`, `heading_path`, `part_index`/`part_total`, `line_start`/`line_end`, `page_id`, `source_version`, `content_hash`, `chunker_version`; `acl_tags` now requires `minItems: 1` |
| RelationRecord | Unified single shape with `resolution_status` and `created_at`; deterministic `relation_id` |
| ACLRecord | `acl_id`, `restriction_inherited`, `restriction_source_page_ids`, `acl_confidence`, `extracted_at` |
| SymbolRecord | `commit_hash`, `parse_status`, `scanned_at` |
| MediaAsset | `raw_uri`, `content_hash`, `source_version`, `updated_at`, `crawled_at`; `not_processed` added to `processing_status` |
| New record types | TombstoneRecord (§16.2), SyncStateRecord (snapshot shape; the authoritative mutable state lives in the SQLite metadata store), Manifest (`dataset_version`, `export_mode`, `base_dataset_version`, `generated_at`, `config_hash`, `chunker_version`, `schemas_version`, `counts`, `source_scopes`) |

Illustrative examples now live next to their sections: ChunkRecord §16.3, RelationRecord §13, ACLRecord §14.4, SymbolRecord §12.2, MediaAsset §11, TombstoneRecord §16.2.

# Appendix B. Practical Prompt for Claude Code Later

When implementation starts, do not ask Claude Code to build the whole platform. Use this spec as master context, then assign one bounded module at a time. Example:

```
Read AI_Knowledge_Platform_Master_Spec_v7_1.md (plus CHUNKING_SPEC.md and schemas/) and implement only the Confluence Inventory MVP.
Scope:
- Load config/confluence_scope.yaml
- Use PAT from environment variable
- Fetch descendants under space SVMC and parent page id 938880621
- Support exclude_subtrees by page id
- Output inventory_report.csv and pages_inventory.jsonl
- Do not download attachments yet
- Add rate limiter and checkpoint
- Add tests with mocked Confluence responses
- Validate every exported record against schemas/*.json (JSON Schema draft 2020-12)
Out of scope:
- Qdrant
- RAG
- final chatbot
- full media processing
```
