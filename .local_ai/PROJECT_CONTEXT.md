# Project Context - KnowledgeNexus / AI Knowledge Platform

## Product

KnowledgeNexus / AI Knowledge Platform is one product repository.

The system is an organization knowledge platform, not only a chatbot. It ingests internal engineering knowledge from Confluence, Git/Gerrit, Jira keys, source code, media, and future sources.

## Current Implementation Focus

We are implementing Foundation / Part 1 first.

Foundation owns:
- source connectors
- raw store
- normalization
- chunking
- ACL extraction
- relation extraction
- media metadata and extraction
- symbol index
- export snapshot

Foundation does not own:
- embedding
- Qdrant upsert
- retrieval
- chat
- Gauss/LLM answer generation

## Repository Architecture

Preferred architecture: single product repository / modular monolith.

Bounded contexts:
- `foundation`: Part 1 data foundation
- `indexing`: Part 2 import/embed/store/Qdrant
- `retrieval`: Part 3 search/rerank/ACL expansion
- `chat`: Part 3 answer generation
- `presentation`: API/CLI entrypoints
- `shared`: technical utilities only

Canonical destination layout is defined in:
- `contracts/foundation/decision_logs/AI_Knowledge_Platform_v7_5_Update.md`

Important: the canonical tree is a destination, not a scaffold. Do not create empty unrelated folders early.

## Contract Boundary

Official Foundation contract root:

```text
contracts/foundation/
```

Important files:
- `contracts/foundation/schemas/`
- `contracts/foundation/CHUNKING_SPEC.md`
- `contracts/foundation/embedding_profile.yaml`
- `contracts/foundation/Task2_Task3_Integration_Contract.md`
- `contracts/foundation/decision_logs/AI_Knowledge_Platform_v7_5_Update.md`

Foundation writes export snapshots to:

```text
data/exports/<dataset_name>/<dataset_version>/
```

Indexing reads only `data/exports`. It must not read `data/raw` or `data/work`.

## Current Coding Phase

Current phase: M5B-2 is implemented, offline-tested, and independently
approved. M0-M4, deployment-independent M5A, M5B-0 live API confirmation, and
M5B-1 pure response parsing/normalization are complete. M5C is the next task and
will perform the small real inventory smoke run on the connected machine.

Implemented Foundation domain rules:
- `ContentHasher`
- `TextNormalizationRules`
- `ChunkIdGenerator`
- `RelationIdGenerator`
- `AclIdGenerator`
- `TombstoneIdGenerator`
- `DocumentIdGenerator`

Implemented shared Foundation contract utilities:
- `shared/contracts/foundation/contract_loader.py`
- `shared/contracts/foundation/schema_validator.py`

Implemented Foundation domain record builders:
- `CanonicalDocumentRecordBuilder`
- `ChunkRecordBuilder`
- `RelationRecordBuilder`
- `ACLRecordBuilder`
- `ManifestRecordBuilder`

Implemented Foundation infrastructure/application boundaries include validated
full-snapshot staging/completion/publication and the M5A Confluence inventory
models, scope policy, port, use case, deterministic JSONL/CSV reports, and the
M5B-1 pure Data Center metadata/envelope parser, the standard-library bounded
HTTPS JSON transport, and the M5B-2 Data Center inventory adapter.

## Confirmed M5B Deployment Evidence

- Confluence Server/Data Center REST family under `/rest/api`.
- Bearer PAT authentication supplied outside M5A config and artifacts.
- Fetch the selected root separately.
- Enumerate descendants with `/rest/api/search` and immutable CQL selectors:
  `space`, `ancestor`, and `type=page`.
- Paginate with validated integer `start`, `limit`, `size`, and `totalSize`;
  `/_links/next` is not reliable for this search endpoint.
- Map ID, title, space key, ordered ancestors/titles, version number/timestamp,
  and labels. Attachment count remains `None`.
- Trim ancestors above the selected root, derive parent from the last remaining
  ancestor, and fail closed for malformed or out-of-scope results.
- Fetch the root with `expand=space,version` and require the returned
  `space.key` to match before yielding it. M5C must confirm this additive root
  expansion because M5B-0 observed only `expand=version`.
- Advance descendant search from validated numeric pagination fields under an
  explicit request-page budget; ignore `_links.next` and allow `totalSize` to
  change between windows.

Current M5B scope excludes page bodies, rendered HTML, comments, attachments,
ACL/permission extraction, retries, rate limiting, checkpoints, resume, content
normalization/chunking, Qdrant, indexing, retrieval, chat, presentation API, and
unrelated bounded-context scaffolding.
