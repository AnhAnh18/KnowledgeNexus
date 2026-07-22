# M6D-D independent review summary

Status: complete and independently approved; no unresolved P0-P2 finding.

Base: `9b4fec070187e373bac7de7e07560a6cf8dc7b0d` (`M6D-C-F`).

## Scope delivered

- Normative M6D-D clarifications for exact sibling merge, collision handling,
  split-code unit keys, and integer nearest-rank metrics.
- `BuildConfluenceChunks.execute(*, canonical_document, structure) ->
  ChunkingResult`, with the profile, tokenizer, ID generator, record builder,
  and schema validator injected.
- Ordered source assembly, exact normalized final-text budgeting, h2/h3
  same-level/same-parent/source-adjacent short merge, forced prose splitting
  with bounded overlap, complete-line code windows, and table row groups.
- Exact canonical metadata mapping, default-deny ACL placeholder, stable ID
  duplicate suffixes, true-collision failure, per-unit part fields, schema
  validation, and deterministic required quality metrics.
- Offline one-page acceptance CLI with explicit page/raw/profile/assets/time
  inputs, repeated execution, fail-closed acceptance invariants, aggregate-only
  output, and no persistence or network component.

Public boundary:

```text
BuildConfluenceChunks(
    profile: ChunkingProfile,
    tokenizer: TokenizerPort,
    chunk_id_generator,
    chunk_record_builder,
    schema_validator,
)

execute(
    canonical_document: Mapping[str, object],
    structure: WikiDocumentStructure,
) -> ChunkingResult

ChunkingResult.records: tuple[dict[str, object], ...]
ChunkingResult.metrics: dict[str, object]
```

All exposed chunking failures carry only a
`ConfluenceChunkingFailureCategory`. No exception message includes source text,
title, page/chunk identity, path, URL, hash, or tokenizer asset location.

## Verification

Environment:

```text
PYTHONUTF8=1
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
Python 3.12 isolated venv under C:\tmp
tokenizer bundle revision: 5617a9f61b028005a4858fdac845db406aefb181
tokenizer.json bytes: 17098108
tokenizer.json SHA-256: 21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08
```

Focused M6D-D suite including the real pinned-BGE paths: 56 passed. The
forced-split integration test re-tokenized every exact emitted record. Full
command:

```text
python -m pytest tests/foundation tests/shared tests/architecture \
  tests/indexing/infrastructure/embedding -q \
  --tokenizer-assets-dir <approved-external-bundle>
```

Result: `1122 passed in 57.21s`; no skip. `git diff --check`: pass.

Post-commit clean-tree verification of every behavior commit:

```text
17c139c  M6D-D-A  1076 passed
e837bf4  M6D-D-B  1112 passed
bacc22a  M6D-D-C  1122 passed
```

Each command used the same offline flags and exact external tokenizer bundle.

The real-bundle CLI composition test runs M6A raw input through M6C, M6D-C,
and M6D-D twice, while blocking network connection creation. It verifies exact
file-tree equality before/after and sanitized output with no identity, content,
path, hash, or URL.

## Boundary confirmation

- Exact external BGE-M3 tokenizer: yes; no implicit cache or network.
- `ChunkRecord` schema validation: every record before success.
- Hard maximum: enforced on exact emitted normalized text; metric remains zero.
- M6F default-deny placeholder only: `restricted:unresolved`.
- Output files: none.
- Relations / M6E: not started.
- Attachment bodies, ACL resolution, media, export, embedding: absent.

## Approved lettered stack

```text
BASE 9b4fec0
  -> 17c139c [M6D-D-A] foundation: lock wiki chunking contract and result boundary
  -> e837bf4 [M6D-D-B] foundation: build deterministic Confluence wiki chunks
  -> bacc22a [M6D-D-C] foundation: add offline one-page chunk acceptance CLI
  -> [M6D-D-D] docs: record M6D-D implementation and review evidence
```

The repository owner authorized this final stack and push after the detached
Approve verdict. M6D-E/M6E relation extraction has not started.
